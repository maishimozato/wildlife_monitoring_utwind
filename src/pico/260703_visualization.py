import rp2                       # rp2 module lets us control the RP2040's special PIO hardware (programmable I/O)
from rp2 import PIO, asm_pio     # PIO = settings/constants for the PIO hardware, asm_pio = decorator to write tiny PIO "assembly" programs
from machine import Pin          # Pin lets us control individual GPIO pins on the board
import micropython                # micropython module gives access to low-level performance/memory features
from uarray import array          # 'array' is a compact, fixed-type list (faster/smaller than a normal Python list)

micropython.alloc_emergency_exception_buf(200)
# reserves a small chunk of memory (200 bytes) so MicroPython can still report
# an error message even if it runs out of memory during an interrupt (like a DMA IRQ).

# ---------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------
PDM_CLK_PIN = 2                  # GPIO pin number that will output the clock signal to the PDM microphone
PDM_DATA_PIN = 3                 # GPIO pin number that will read the 1-bit audio data coming from the microphone

PIO_NUM = 0                      # which PIO block to use (RP2040 has two: PIO0 and PIO1) - we use PIO0
SM_NUM = 0                       # which "state machine" inside that PIO block to use (each PIO has 4) - we use state machine 0

CIC_ORDER = 2                    # order (number of integrator/comb stages) of the CIC filter used to turn 1-bit PDM into real audio samples
CIC_DECIM = 16                   # decimation factor: how many raw 1-bit samples are combined into one output audio sample
CIC_GAIN_SHIFT = 4               # how many bits to shift right at the end, to bring the filter's big numbers back down to a normal audio range

WORDS_PER_BUF = 2048             # number of 32-bit words to store in each DMA buffer before it's considered "full"
BYTES_PER_BUF = WORDS_PER_BUF * 4  # same size but expressed in bytes (each word = 4 bytes), used to allocate memory

PIO0_BASE = 0x50200000           # fixed hardware memory address where PIO0's registers live (from the RP2040 datasheet)
PIO1_BASE = 0x50300000           # fixed hardware memory address where PIO1's registers live
PIO_BASE = PIO0_BASE if PIO_NUM == 0 else PIO1_BASE
# pick the correct base address depending on which PIO block we configured above (PIO_NUM)

RXF_ADDR = PIO_BASE + 0x20 + 4 * SM_NUM
# calculate the exact memory address of the "RX FIFO" register for our chosen state machine.
# this is the address DMA will read from to grab incoming PDM data.

DREQ_PIO_RX = (4 if PIO_NUM == 0 else 12) + SM_NUM
# DREQ = "Data Request" signal number. This tells the DMA controller exactly which
# hardware event ("PIO0 state machine 0 has new data") should trigger a data transfer.

# ---------------------------------------------------------------------
# PIO program
# ---------------------------------------------------------------------
@asm_pio(
    sideset_init=PIO.OUT_LOW,      # the "side-set" pin (our clock pin) starts in the LOW (0V) state
    in_shiftdir=PIO.SHIFT_LEFT,    # new bits we read get shifted in from the right, pushing older bits left
    autopush=True,                 # automatically push (send) data to the FIFO once enough bits are collected, no manual push needed
    push_thresh=32,                # push data to the FIFO after every 32 bits have been collected (fills a full word)
    fifo_join=PIO.JOIN_RX,         # combine the TX and RX FIFOs into one bigger RX FIFO, since we only receive data (not send)
)
def pdm_capture():
    wrap_target()                  # marks the start of the loop that will repeat forever
    in_(pins, 1)    .side(1)       # read 1 bit from the data pin, and at the same time set the clock pin HIGH
    nop()           .side(0)       # do nothing for one cycle, and set the clock pin LOW (this creates the clock's up/down pulse)
    wrap()                         # marks the end of the loop - jumps back to wrap_target(), repeating forever

sm = rp2.StateMachine(
    PIO_NUM * 4 + SM_NUM,          # global state machine ID (PIO block * 4 slots + state machine number)
    pdm_capture,                   # the PIO program we just defined above
    freq=6_144_000,                # clock speed for this state machine: 6.144 MHz (this becomes the microphone's PDM clock rate)
    sideset_base=Pin(PDM_CLK_PIN), # which physical pin the "side-set" (clock) output controls
    in_base=Pin(PDM_DATA_PIN),     # which physical pin the "in_" (data input) instruction reads from
)

# ---------------------------------------------------------------------
# DMA ping-pong
# ---------------------------------------------------------------------
raw_buf = [bytearray(BYTES_PER_BUF), bytearray(BYTES_PER_BUF)]
# two raw memory buffers (byte arrays) that will hold incoming PDM data.
# we use two so one can be filled by DMA while the other is being processed ("ping-pong" buffering).

buf_ready = [False, False]
# flags that track whether each buffer has been completely filled and is ready to be processed.

dma = [rp2.DMA(), rp2.DMA()]
# grab two DMA (Direct Memory Access) channels - hardware that can copy data
# from the PIO FIFO into our buffers without the CPU having to do it manually.

def _make_ctrl(chan_idx):
    # builds the configuration word for one DMA channel, given its index (0 or 1).
    other = dma[1 - chan_idx]
    # get a reference to the "other" DMA channel (if this is channel 0, other is channel 1, and vice versa).
    return dma[chan_idx].pack_ctrl(
        size=2,                    # transfer size = 2 means "4 bytes at a time" (32-bit words)
        inc_read=False,            # don't move the read address forward - always read from the same PIO FIFO register
        inc_write=True,            # do move the write address forward - fill the buffer byte by byte/word by word
        treq_sel=DREQ_PIO_RX,      # only transfer when the PIO signals "I have new data" (paces the DMA to match the mic's data rate)
        chain_to=other.channel,    # when this channel finishes, automatically start the other channel (creates the ping-pong effect)
        irq_quiet=False,           # allow this channel to raise an interrupt when it finishes (so our code gets notified)
    )

def _irq_handler(which):
    # creates a custom interrupt handler function for a specific buffer index ("which" = 0 or 1).
    def handler(dma_chan):
        buf_ready[which] = True
        # when DMA finishes filling this buffer, just mark it as "ready" - keep the actual work minimal since this runs during an interrupt.
    return handler

dma[0].irq(handler=_irq_handler(0))
# tell DMA channel 0 to call our handler (which marks buffer 0 ready) whenever it finishes a transfer.
dma[1].irq(handler=_irq_handler(1))
# same thing for DMA channel 1 and buffer 1.

def _arm(chan_idx):
    # "Arms" (sets up and starts) one DMA channel to begin filling its buffer again.
    dma[chan_idx].config(
        read=RXF_ADDR,              # where to read data from: the PIO's RX FIFO register
        write=raw_buf[chan_idx],    # where to write data to: this channel's buffer
        count=WORDS_PER_BUF,        # how many words to transfer before stopping (buffer size)
        ctrl=_make_ctrl(chan_idx),  # the control settings we built above
        trigger=(chan_idx == 0),    # only immediately start channel 0; channel 1 will be triggered later by chaining
    )

_arm(0)                          # set up and start DMA channel 0 right away
_arm(1)                          # set up DMA channel 1 (it will kick in automatically once channel 0 finishes, via chaining)

sm.active(1)                     # turn on the PIO state machine, so it actually starts clocking out data and reading the mic

# ---------------------------------------------------------------------
# CIC decimator + level metering, all in one viper pass for speed.
# returns packed (peak << 16) | rms so viper can return a single int.
# ---------------------------------------------------------------------
cic_state = array('i', [0] * (2 * CIC_ORDER + 1))
# create an array of 5 signed integers, all starting at 0.
# holds the CIC filter's "memory" between processing calls (integrator/comb values + bit counter).

@micropython.viper
# @micropython.viper compiles this function to much faster, more C-like machine code -
# needed here because we're processing thousands of bits per audio buffer.
def cic_process_and_meter(raw: ptr32, n_words: int, state: ptr32) -> int:
    # raw = pointer to the raw PDM buffer (as 32-bit words), n_words = how many words to process,
    # state = pointer to our saved filter state; returns a single packed integer result.

    integ0 = state[0]            # load the first integrator stage's running total from saved state
    integ1 = state[1]            # load the second integrator stage's running total from saved state
    comb0 = state[2]             # load the first comb stage's previous value from saved state
    comb1 = state[3]             # load the second comb stage's previous value from saved state
    bit_count = state[4]         # load how many raw bits have been counted since the last output sample
    decim = int(CIC_DECIM)       # copy the decimation factor into a local variable (faster access in the loop)
    gain_shift = int(CIC_GAIN_SHIFT)  # copy the gain shift amount into a local variable

    peak = 0                     # will track the loudest (largest absolute) sample seen in this buffer
    sumsq = 0                    # will accumulate the sum of each sample squared (used to compute RMS/volume)
    n_out = 0                    # counts how many actual audio samples were produced from this buffer

    i = 0                        # index into the raw 32-bit word array
    while i < n_words:           # loop over every word in the buffer
        word = raw[i]             # grab the current 32-bit word (32 raw PDM bits) from memory
        b = 31                    # start looking at the highest bit (bit 31) within this word
        while b >= 0:              # loop through all 32 bits of this word, one at a time
            bit = (word >> b) & 1  # extract just bit number "b" from the word (shift it down, then mask off everything else)
            x = 1 if bit else -1   # convert the 1-bit PDM sample into +1 (if bit is 1) or -1 (if bit is 0)

            integ0 += x            # first integrator stage: keep adding up the incoming +1/-1 values
            integ1 += integ0       # second integrator stage: keep adding up the output of the first integrator

            bit_count += 1         # processed one more raw bit since the last output sample
            if bit_count >= decim:  # after collected enough raw bits (decim of them)...
                bit_count = 0        # ...reset the counter to start counting toward the next output sample
                y = integ1            # take a "snapshot" of the second integrator's current value
                t0 = y                 # remember this snapshot temporarily
                y = y - comb0          # first comb stage: subtract the previous snapshot (this differentiates/filters the signal)
                comb0 = t0             # save this snapshot for next time (becomes "previous" for the next round)
                t1 = y                  # remember the result of the first comb stage
                y = y - comb1            # second comb stage: subtract the previous first-comb result
                comb1 = t1               # save this result for next time

                scaled = y >> gain_shift # Shift the big filtered value down to bring it into a normal 16-bit-ish audio range
                if scaled > 32767:        # clamp: don't let the value go above the max for a 16-bit signed sample
                    scaled = 32767
                if scaled < -32768:        # clamp: don't let the value go below the min for a 16-bit signed sample
                    scaled = -32768

                a = scaled if scaled >= 0 else -scaled  # compute the absolute value of this sample (its loudness, ignoring sign)
                if a > peak:                              # if this sample is louder than any we've seen so far in this buffer...
                    peak = a                                # ...update our running "peak" (loudest sample) value
                sumsq += scaled * scaled                   # add this sample's square to our running total (needed to compute RMS later)
                n_out += 1                                 
            b -= 1                 # move on to the next lower bit within this word
        i += 1                    # move on to the next word in the buffer

    state[0] = integ0            # save the first integrator's value back into state, for use next time this function is called
    state[1] = integ1            # save the second integrator's value back into state
    state[2] = comb0             # save the first comb stage's value back into state
    state[3] = comb1             # save the second comb stage's value back into state
    state[4] = bit_count         # save the leftover bit counter back into state

    mean_sq = sumsq // n_out if n_out > 0 else 0
    # compute the average of the squared samples (mean square) - but only if we actually produced samples, to avoid dividing by zero.

    # integer sqrt
    rms = 0                      # hold the square root of mean_sq, i.e. the RMS (loudness) value
    if mean_sq > 0:               # only bother computing a square root if there's actually a nonzero value
        x0 = mean_sq                # keep the original value handy for the iterative formula below
        r = mean_sq                  # start our guess for the square root at the value itself (will shrink quickly)
        while True:                   # repeat using Newton's method (integer version) until the guess stops improving
            r2 = (r + x0 // r) // 2     # compute a better guess for the square root
            if r2 >= r:                  # if the new guess isn't smaller than the old one, we've converged
                break                     # stop the loop - we have our answer
            r = r2                        # otherwise, keep the improved guess and try again
        rms = r                        # store the final square root result as our RMS value

    return (peak << 16) | (rms & 0xFFFF)
    # pack both results into a single integer so viper can return just one value:
    # the top 16 bits hold "peak", the bottom 16 bits hold "rms".

# ---------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------
print("starting - clap!!! (pls work)")
# print a startup message to the console so we know the script is running.

while True:                      # loop forever, continuously checking for new audio data
    for idx in (0, 1):             # check both buffers (0 and 1) each time through the loop
        if buf_ready[idx]:           # if this buffer has been completely filled by DMA...
            buf_ready[idx] = False     # ...clear the flag immediately so we don't process it twice
            packed = cic_process_and_meter(raw_buf[idx], WORDS_PER_BUF, cic_state)
            # run our fast filter+metering function on this buffer, getting back the packed peak/rms result

            _arm(idx)                  # re-arm this DMA channel right away so it can start refilling this buffer with new data
            peak = packed >> 16        # extract the "peak" value from the upper 16 bits of the packed result
            rms = packed & 0xFFFF      # extract the "rms" value from the lower 16 bits of the packed result
            print(peak, rms)           # print both values so we can see the microphone's loudness in real time
