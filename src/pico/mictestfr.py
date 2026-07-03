# main_standalone_test.py - Pico bat detector, STANDALONE TEST VERSION
#
# Same PIO/DMA/CIC pipeline as the real main.py, but instead of streaming
# raw PCM over USB (which needs the Pi 4 on the other end), this version
# prints periodic level stats to the REPL and blinks the onboard LED
# based on signal strength. Use this to confirm mic + PIO + DMA + CIC
# are all working before you hook up the Pi.
#
# Wiring (same as before):
#   GPIO2 -> mic CLK
#   GPIO3 <- mic DATA
#   3V3   -> mic VDD
#   GND   -> mic GND, SELECT
#
# HOW TO TEST:
#   1. Save this as main.py on the Pico (or run it directly from Thonny).
#   2. Open a serial terminal (Thonny's Shell, or `screen`/`picocom`).
#   3. You should see periodic lines like:
#        buf#   120  rate: 187.4 Hz  peak: 4213  rms:  812
#   4. Tap the mic, talk near it, jingle keys, clap - "peak" and "rms"
#      should jump noticeably when there's sound, and the LED should
#      get brighter/blink faster. If they never move off near-zero,
#      the signal chain (wiring, PIO, or CIC gain) needs a look before
#      you bother connecting the Pi.
#   5. "rate" should hover near 187-192 (WORDS_PER_BUF*32/CIC_DECIM /
#      buffer_period, i.e. your PCM sample rate divided down per
#      buffer). If it's wildly off or erratic, DMA is stalling/dropping.
#
# Requires MicroPython >= 1.21 (rp2.DMA support).

import rp2
from rp2 import PIO, asm_pio
from machine import Pin
import time
import micropython
from uarray import array

micropython.alloc_emergency_exception_buf(200)

# ---------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------
PDM_CLK_PIN = 2
PDM_DATA_PIN = 3

PIO_NUM = 0
SM_NUM = 0

CIC_ORDER = 2
CIC_DECIM = 16          # PDM_CLK / CIC_DECIM = PCM rate (3.072MHz/16 = 192kHz)
CIC_GAIN_SHIFT = 4      # TUNE THIS on real hardware, see README

WORDS_PER_BUF = 2048     # raw 32-bit PDM words per DMA half-buffer
BYTES_PER_BUF = WORDS_PER_BUF * 4

PRINT_EVERY_N_BUFS = 10  # how often to print stats (avoid REPL flooding)

PIO0_BASE = 0x50200000
PIO1_BASE = 0x50300000
PIO_BASE = PIO0_BASE if PIO_NUM == 0 else PIO1_BASE
RXF_ADDR = PIO_BASE + 0x20 + 4 * SM_NUM   # RXF0..3 register

# DREQ numbers per RP2040 datasheet: PIO0 RX0-3 = 4-7, PIO1 RX0-3 = 12-15
DREQ_PIO_RX = (4 if PIO_NUM == 0 else 12) + SM_NUM

# ---------------------------------------------------------------------
# Onboard LED - Pico and Pico W expose this differently, so try both
# ---------------------------------------------------------------------
try:
    led = Pin("LED", Pin.OUT)      # Pico W (and some newer MicroPython builds)
except (ValueError, TypeError):
    led = Pin(25, Pin.OUT)         # original Pico

led.value(0)

# ---------------------------------------------------------------------
# PIO program: generate PDM_CLK (side-set), sample DATA into ISR
# ---------------------------------------------------------------------
@asm_pio(
    sideset_init=PIO.OUT_LOW,
    in_shiftdir=PIO.SHIFT_LEFT,
    autopush=True,
    push_thresh=32,
    fifo_join=PIO.JOIN_RX,
)
def pdm_capture():
    wrap_target()
    in_(pins, 1)    .side(1)
    nop()           .side(0)
    wrap()

sm = rp2.StateMachine(
    PIO_NUM * 4 + SM_NUM,
    pdm_capture,
    freq=6_144_000,          # SM clock; PDM_CLK = freq/2 = 3.072MHz
    sideset_base=Pin(PDM_CLK_PIN),
    in_base=Pin(PDM_DATA_PIN),
)

# ---------------------------------------------------------------------
# DMA: two channels ping-ponging into two raw-word buffers
# ---------------------------------------------------------------------
raw_buf = [bytearray(BYTES_PER_BUF), bytearray(BYTES_PER_BUF)]
buf_ready = [False, False]

dma = [rp2.DMA(), rp2.DMA()]

def _make_ctrl(chan_idx):
    other = dma[1 - chan_idx]
    return dma[chan_idx].pack_ctrl(
        size=2,                 # 2 = 32-bit transfers
        inc_read=False,         # always reading the same FIFO register
        inc_write=True,
        treq_sel=DREQ_PIO_RX,
        chain_to=other.channel,
        irq_quiet=False,
    )

def _irq_handler(which):
    def handler(dma_chan):
        buf_ready[which] = True
    return handler

dma[0].irq(handler=_irq_handler(0))
dma[1].irq(handler=_irq_handler(1))

def _arm(chan_idx, trigger=False):
    dma[chan_idx].config(
        read=RXF_ADDR,
        write=raw_buf[chan_idx],
        count=WORDS_PER_BUF,
        ctrl=_make_ctrl(chan_idx),
        trigger=trigger,
    )

_arm(0, trigger=True)
_arm(1, trigger=False)

sm.active(1)

# ---------------------------------------------------------------------
# CIC decimator - viper for speed. State (integrators/combs) lives in a
# small int array passed in each call so it persists across buffers.
# ---------------------------------------------------------------------
# state layout: [integ_0, integ_1, comb_delay_0, comb_delay_1, bit_count]
cic_state = array('i', [0] * (2 * CIC_ORDER + 1))

pcm_out = array('h', [0] * (WORDS_PER_BUF * 32 // CIC_DECIM + 4))

@micropython.viper
def cic_process(raw: ptr32, n_words: int, state: ptr32, out: ptr16) -> int:
    integ0 = state[0]
    integ1 = state[1]
    comb0 = state[2]
    comb1 = state[3]
    bit_count = state[4]
    out_idx = 0
    decim = int(CIC_DECIM)
    gain_shift = int(CIC_GAIN_SHIFT)

    i = 0
    while i < n_words:
        word = raw[i]
        b = 31
        while b >= 0:
            bit = (word >> b) & 1
            x = 1 if bit else -1

            integ0 += x
            integ1 += integ0

            bit_count += 1
            if bit_count >= decim:
                bit_count = 0
                y = integ1
                t0 = y
                y = y - comb0
                comb0 = t0
                t1 = y
                y = y - comb1
                comb1 = t1

                scaled = y >> gain_shift
                if scaled > 32767:
                    scaled = 32767
                if scaled < -32768:
                    scaled = -32768
                out[out_idx] = scaled
                out_idx += 1
            b -= 1
        i += 1

    state[0] = integ0
    state[1] = integ1
    state[2] = comb0
    state[3] = comb1
    state[4] = bit_count
    return out_idx

# ---------------------------------------------------------------------
# Stats helper - plain Python is fine here since it only runs once
# every PRINT_EVERY_N_BUFS buffers, not per-sample.
# ---------------------------------------------------------------------
def _peak_and_rms(buf, n):
    peak = 0
    sumsq = 0.0  # float accumulator - plain ints can overflow/wrap on this build
    for i in range(n):
        v = buf[i]
        av = v if v >= 0 else -v
        if av > peak:
            peak = av
        fv = float(v)
        sumsq += fv * fv
    if n == 0:
        return 0, 0
    mean_sq = sumsq / n
    rms = int(mean_sq ** 0.5) if mean_sq > 0 else 0
    return peak, rms

# ---------------------------------------------------------------------
# Main loop: wait for a filled DMA buffer, decimate it, print stats
# ---------------------------------------------------------------------
buf_count = 0
last_print_ms = time.ticks_ms()

print("Standalone test running. Make noise near the mic...")

while True:
    for idx in (0, 1):
        if buf_ready[idx]:
            buf_ready[idx] = False
            n_samples = cic_process(raw_buf[idx], WORDS_PER_BUF, cic_state, pcm_out)
            # re-arm this DMA channel for the next fill of this buffer
            _arm(idx, trigger=False)

            buf_count += 1

            peak, rms = _peak_and_rms(pcm_out, n_samples)

            # crude LED feedback: brighter/faster blink with louder signal
            led.value(1 if peak > 500 else 0)

            if buf_count % PRINT_EVERY_N_BUFS == 0:
                now = time.ticks_ms()
                elapsed = time.ticks_diff(now, last_print_ms) / 1000.0
                rate = (PRINT_EVERY_N_BUFS / elapsed) if elapsed > 0 else 0.0
                last_print_ms = now
                print("buf#{:6d}  rate: {:6.1f} Hz  peak: {:6d}  rms: {:6d}"
                      .format(buf_count, rate, peak, rms))
