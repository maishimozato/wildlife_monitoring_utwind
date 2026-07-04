# main.py - Pico bat detector, MicroPython version

import rp2                       # RP2040-specific hardware module: gives us PIO and DMA access
from rp2 import PIO, asm_pio     # PIO = pin/state-machine config constants; asm_pio = decorator that compiles PIO assembly
from machine import Pin          # Pin lets us refer to a GPIO pin by number
import sys                       # used below to get raw access to the USB serial output stream
import uctypes                   # low-level C-style struct/memory access (imported but not directly used further down)
import micropython                # gives us micropython.viper (fast native-code compilation) and buffer helpers
from uarray import array          # uarray.array = compact, fixed-type array (like C arrays), fast and memory-light

micropython.alloc_emergency_exception_buf(200)
# reserves 200 bytes of memory ahead of time so that if an exception happens INSIDE an
# interrupt handler (like the DMA IRQ below), MicroPython has somewhere to store the
# error message. Interrupt handlers can't safely allocate memory on the fly.

# ---------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------
PDM_CLK_PIN = 2                  # GPIO pin number wired to the mic's CLK input
PDM_DATA_PIN = 3                 # GPIO pin number wired to the mic's DATA output

PIO_NUM = 0                      # which PIO hardware block to use: the RP2040 has PIO0 and PIO1
SM_NUM = 0                       # which state machine (0-3) within that PIO block to use

CIC_ORDER = 2                    # number of integrator/comb stages in the CIC filter (see caveats above)
CIC_DECIM = 16                   # PDM_CLK / CIC_DECIM = PCM rate (3.072MHz/16 = 192kHz)
CIC_GAIN_SHIFT = 4               # TUNE THIS on real hardware, see README - right-shift amount to scale filter output to audio range

WORDS_PER_BUF = 2048             # raw 32-bit PDM words per DMA half-buffer (i.e. per ping-pong buffer)
BYTES_PER_BUF = WORDS_PER_BUF * 4  # same size in bytes, since each word is 4 bytes (32 bits)

# --- debug mode: print decoded PCM integers directly to the REPL/serial console ---
# instead of streaming raw binary bytes to a host script. Useful for sanity-checking
# that samples are actually varying (mic + CIC path working) before wiring up the
# Python-side detector again.
DEBUG_PRINT = True                # set False to go back to raw binary usb.write() streaming
DEBUG_PRINT_EVERY_N_BUFS = 8      # only print for 1 out of every N filled buffers (throttles REPL output)
DEBUG_PRINT_SAMPLES = 16          # how many samples from that buffer to print each time

PIO0_BASE = 0x50200000           # fixed hardware memory address where PIO0's registers live (from the RP2040 datasheet)
PIO1_BASE = 0x50300000           # fixed hardware memory address where PIO1's registers live
PIO_BASE = PIO0_BASE if PIO_NUM == 0 else PIO1_BASE   # pick the base address matching PIO_NUM above
RXF_ADDR = PIO_BASE + 0x20 + 4 * SM_NUM   # RXF0..3 register - address of this state machine's "data received" FIFO register

# DREQ numbers per RP2040 datasheet: PIO0 RX0-3 = 4-7, PIO1 RX0-3 = 12-15
DREQ_PIO_RX = (4 if PIO_NUM == 0 else 12) + SM_NUM
# DREQ = "data request" line number. Tells the DMA hardware which peripheral signal to
# wait on before moving each word, so it's paced by the PIO instead of running unthrottled.

# ---------------------------------------------------------------------
# PIO program: generate PDM_CLK (side-set), sample DATA into ISR
# ---------------------------------------------------------------------
@asm_pio(
    sideset_init=PIO.OUT_LOW,    # the "side-set" pin (CLK) starts in the low state
    in_shiftdir=PIO.SHIFT_LEFT,  # incoming bits shift into the input register from the right, building left-to-right
    autopush=True,               # automatically push a full word to the RX FIFO once enough bits are collected
    push_thresh=32,              # "enough bits" = 32, i.e. push after each full 32-bit word is assembled
    fifo_join=PIO.JOIN_RX,       # merge the TX FIFO's space into the RX FIFO since we never transmit, only receive
)
def pdm_capture():
    wrap_target()                 # marks the top of the loop (where "wrap()" below jumps back to)
    in_(pins, 1)    .side(1)      # read 1 bit from the DATA pin into the shift register; simultaneously drive CLK HIGH
    nop()           .side(0)      # do nothing this cycle, except drive CLK LOW (completes one clock pulse)
    wrap()                        # loop back to wrap_target() forever - this is the whole PDM bit-banging program

sm = rp2.StateMachine(
    PIO_NUM * 4 + SM_NUM,          # global state machine index (0-7 across both PIO blocks)
    pdm_capture,                   # the compiled PIO program to run on it
    freq=6_144_000,                # SM clock; PDM_CLK = freq/2 = 3.072MHz (2 instructions per clock pulse)
    sideset_base=Pin(PDM_CLK_PIN), # which physical pin the side-set (CLK) output drives
    in_base=Pin(PDM_DATA_PIN),     # which physical pin the "in_" instruction reads from
)

# ---------------------------------------------------------------------
# DMA: two channels ping-ponging into two raw-word buffers
# ---------------------------------------------------------------------
raw_buf = [bytearray(BYTES_PER_BUF), bytearray(BYTES_PER_BUF)]
# two raw byte buffers - one filled while the other is being processed (double buffering)

buf_ready = [False, False]
# flags set by the DMA interrupt handlers to tell the main loop "this buffer is full"

dma = [rp2.DMA(), rp2.DMA()]
# two DMA channel objects, one per buffer

def _make_ctrl(chan_idx):
    other = dma[1 - chan_idx]                # the "other" channel, used for auto-chaining below
    return dma[chan_idx].pack_ctrl(
        size=2,                              # 2 = 32-bit transfers (0=byte, 1=half-word, 2=word)
        inc_read=False,                      # always reading the same FIFO register - don't advance the read address
        inc_write=True,                      # do advance the write address, filling the buffer sequentially
        treq_sel=DREQ_PIO_RX,                # pace transfers using the PIO's "data ready" signal
        chain_to=other.channel,              # when this channel finishes, automatically start the other one
        irq_quiet=False,                     # raise an interrupt when this channel's transfer completes
    )
    # pack_ctrl() bundles all these settings into the single 32-bit "control register" value DMA hardware expects

def _irq_handler(which):
    def handler(dma_chan):        # dma_chan = the DMA channel object that triggered this interrupt (unused here)
        buf_ready[which] = True   # just flip the flag - keep interrupt handlers as short as possible
    return handler
    # this outer function exists so each handler "remembers" which buffer index (0 or 1) it belongs to

dma[0].irq(handler=_irq_handler(0))   # register the handler for channel 0's completion interrupt
dma[1].irq(handler=_irq_handler(1))   # register the handler for channel 1's completion interrupt

def _arm(chan_idx, initial=False):
    # FIX: `trigger` must only ever be True for the one-time startup kick of channel 0.
    # Previously this was `trigger=(chan_idx == 0)`, which re-triggered channel 0 by
    # software EVERY time it was re-armed in the steady-state loop below - including
    # at the same moment channel 0's own `chain_to` had already auto-started channel 1
    # in hardware. That put both DMA channels racing to drain the same PIO RX FIFO at
    # once, corrupting/stalling the capture so the CIC filter kept seeing a frozen
    # (effectively all-zero) bitstream - which is exactly why the PCM output was a
    # constant, unchanging value instead of real audio.
    #
    # Now: only the very first call (`initial=True`) is allowed to trigger anything by
    # software. After that, each channel's own hardware `chain_to` is solely responsible
    # for re-starting it once the other channel finishes - `_arm()` just resets the
    # buffer/count/ctrl for the *next* fill, without touching the trigger.
    dma[chan_idx].config(
        read=RXF_ADDR,                   # always read from the PIO's RX FIFO register
        write=raw_buf[chan_idx],         # write into this channel's buffer
        count=WORDS_PER_BUF,             # transfer this many words, then stop (and fire the IRQ)
        ctrl=_make_ctrl(chan_idx),       # apply the control settings built above
        trigger=(initial and chan_idx == 0),  # only true once, at startup, and only for channel 0
    )

_arm(0, initial=True)   # configure AND start channel 0 filling raw_buf[0] (one-time kickoff)
_arm(1, initial=True)   # configure channel 1 (armed but not triggered - starts via chain_to once channel 0 finishes)

sm.active(1)
# turns the PIO state machine on: the clock starts pulsing and bits start flowing into the DMA chain

# ---------------------------------------------------------------------
# CIC decimator - viper for speed. State (integrators/combs) lives in a
# small int array passed in each call so it persists across buffers.
# ---------------------------------------------------------------------
# state layout: [integ_0, integ_1, comb_delay_0, comb_delay_1, bit_count]
cic_state = array('i', [0] * (2 * CIC_ORDER + 1))
# 'i' = signed 32-bit int array. Holds the filter's running memory between calls to cic_process,
# since audio is processed in separate chunks (buffers) but the filter must behave as one continuous stream.

pcm_out = array('h', [0] * (WORDS_PER_BUF * 32 // CIC_DECIM + 4))
# 'h' = signed 16-bit int array (standard PCM audio sample format).
# Size = (bits per buffer / decimation factor) = number of output samples one input buffer will yield, plus a small margin.

@micropython.viper
# @micropython.viper compiles this function to native machine code instead of interpreting it,
# which is required to keep up with the incoming bit rate. Type annotations below (ptr32, int, ptr16)
# tell the viper compiler exactly how to treat each argument in memory.
def cic_process(raw: ptr32, n_words: int, state: ptr32, out: ptr16) -> int:
    # raw: pointer to the input buffer, viewed as an array of 32-bit words
    # n_words: how many 32-bit words are in that buffer
    # state: pointer to the persistent filter state array
    # out: pointer to the output buffer, viewed as an array of 16-bit samples
    # returns: how many output samples were actually produced

    integ0 = state[0]        # load integrator stage 1's running value from saved state
    integ1 = state[1]        # load integrator stage 2's running value from saved state
    comb0 = state[2]         # load comb stage 1's delayed value from saved state
    comb1 = state[3]         # load comb stage 2's delayed value from saved state
    bit_count = state[4]     # load how many bits have been accumulated since the last output sample
    out_idx = 0               # index into the output array - counts how many samples we've written so far
    decim = int(CIC_DECIM)          # local copy of the decimation factor (helps viper generate faster code)
    gain_shift = int(CIC_GAIN_SHIFT)  # local copy of the gain shift amount

    i = 0
    while i < n_words:        # outer loop: one iteration per 32-bit word in the input buffer
        word = raw[i]          # load the current 32-bit word (32 raw PDM bits) from the buffer
        b = 31                 # start at the most-significant bit (bit 31)
        while b >= 0:           # inner loop: process each of the 32 bits in this word, MSB first
            bit = (word >> b) & 1   # extract bit number b: shift it down to position 0, then mask off everything else
            x = 1 if bit else -1    # convert the raw bit to +1 (for a 1) or -1 (for a 0) - standard PDM decoding trick

            integ0 += x         # integrator stage 1: running sum of the +1/-1 samples
            integ1 += integ0    # integrator stage 2: running sum of stage 1's output (cascaded integrators)

            bit_count += 1              # one more raw bit has been folded into the integrators
            if bit_count >= decim:      # only produce an output sample once every `decim` (16) input bits
                bit_count = 0            # reset the counter for the next group of 16 bits
                y = integ1                # take the current integrator output as the starting value
                t0 = y                    # remember this value - it becomes comb0's "previous" value next time
                y = y - comb0              # comb stage 1: subtract the value from `decim` samples ago
                comb0 = t0                 # store this cycle's pre-subtraction value for next time
                t1 = y                     # remember this value - it becomes comb1's "previous" value next time
                y = y - comb1               # comb stage 2: second subtraction (cascaded combs, matching 2 integrators)
                comb1 = t1                  # store this cycle's pre-subtraction value for next time

                scaled = y >> gain_shift    # shift right = divide by 2^gain_shift, bringing the value into audio range
                if scaled > 32767:          # clamp to the maximum a signed 16-bit sample can hold
                    scaled = 32767
                if scaled < -32768:         # clamp to the minimum a signed 16-bit sample can hold
                    scaled = -32768
                out[out_idx] = scaled       # write the finished sample into the output buffer
                out_idx += 1                 # advance the output index for the next sample
            b -= 1              # move to the next bit down (bit 30, 29, ... 0)
        i += 1                  # move to the next 32-bit word in the input buffer

    state[0] = integ0     # save integrator 1's value back to persistent state for the next call
    state[1] = integ1     # save integrator 2's value back to persistent state
    state[2] = comb0      # save comb 1's delayed value back to persistent state
    state[3] = comb1      # save comb 2's delayed value back to persistent state
    state[4] = bit_count  # save the partial bit count back to persistent state
    return out_idx        # tell the caller how many valid samples are sitting in `out`

# ---------------------------------------------------------------------
# Main loop: wait for a filled DMA buffer, decimate it, write PCM to USB
# ---------------------------------------------------------------------
usb = sys.stdout.buffer
# raw byte-level handle to the USB serial connection (bypasses text encoding -
# this is the same connection normally used for the REPL, per the caveats above)

buf_count = 0
# counts every filled buffer we've processed, used to throttle how often we print in debug mode
# (printing every buffer, or every sample, is both too slow for MicroPython's print() to keep up
# with and way too much scrollback to read - we only want a periodic sample of real numbers)

while True:                                # run forever
    for idx in (0, 1):                      # check both buffers each pass through the loop
        if buf_ready[idx]:                   # has the DMA interrupt marked this buffer as full?
            buf_ready[idx] = False            # clear the flag immediately so we don't process it twice
            n_samples = cic_process(raw_buf[idx], WORDS_PER_BUF, cic_state, pcm_out)
            # run the CIC filter over the raw bits in this buffer, producing PCM samples in pcm_out
            # re-arm this DMA channel for the next fill of this buffer (does NOT re-trigger;
            # the other channel's chain_to is what restarts this one - see _arm() comments above)
            _arm(idx)                          # reset this DMA channel so it's ready to capture again


            #THIS PRINTS THE VALUES, SET TO FALSE AT TOP TO REMOVEEEEE
            if DEBUG_PRINT:
                buf_count += 1                                  # one more buffer has been processed
                if buf_count % DEBUG_PRINT_EVERY_N_BUFS == 0:    # only print every Nth buffer
                    n_to_show = min(DEBUG_PRINT_SAMPLES, n_samples)  # don't slice past what's actually valid
                    # pcm_out is a uarray('h', ...) of signed 16-bit ints - slicing it and printing
                    # gives you the plain decimal integers directly, no hex/binary decoding needed.
                    # this uses MicroPython's normal text print(), which is slow, hence the throttling above.
                    print(list(pcm_out[:n_to_show]))
            else:
                usb.write(memoryview(pcm_out)[: n_samples * 2])
                # write only the valid portion of pcm_out out over USB, as raw bytes.
                # `n_samples * 2` because each 16-bit sample is 2 bytes; memoryview avoids copying the data.

