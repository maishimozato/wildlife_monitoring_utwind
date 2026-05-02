# SPH0641LU4H-1 on Pico 2: CLK=GPIO2, DATA=GPIO3, SEL=GND, VDD=3V3.
#
# Stock MicroPython does not expose the RP2040/RP2350 PDM peripheral, so this
# uses PIO to (1) drive the mic clock and (2) sample DATA once per clock bit,
# in lockstep — unlike polling Pin.value() in Python, which is meaningless for PDM.
#
# Output is a practical loudness proxy (high-passed bit density), not broadcast PCM.
# For real audio, use a C SDK / OpenPDM2PCM-style pipeline or a firmware with PDM RX.

import time

import rp2
from machine import Pin

PDM_CLK_GPIO = 2
PDM_DATA_GPIO = 3

# Maps high-passed |density - dc| into 0..100 (not dB SPL). Raise if too quiet; lower if it pegs at 100 often.
_LOUDNESS_SCALE = 500.0
# Display smoothing (0..1); higher = calmer needle, slower to react.
_LOUDNESS_SMOOTH = 0.88

# Datasheet "standard performance" PDM clock on CLK pin: ~1.024–2.475 MHz (often 2.4 MHz).
# This PIO program runs 3 SM cycles per full CLK cycle: in_(sample), set high, set low.
_PDM_CLK_HZ = 2_400_000
_SM_FREQ = _PDM_CLK_HZ * 3


@rp2.asm_pio(
    set_init=rp2.PIO.OUT_LOW,
    autopush=True,
    push_thresh=32,
)
def pdm_bit_capture():
    wrap_target()
    in_(pins, 1)
    set(pins, 1)
    set(pins, 0)
    wrap()


def _popcount_u32(x):
    x &= 0xFFFFFFFF
    x = x - ((x >> 1) & 0x55555555)
    x = (x & 0x33333333) + ((x >> 2) & 0x33333333)
    x = (x + (x >> 4)) & 0x0F0F0F0F
    return ((x * 0x01010101) & 0xFFFFFFFF) >> 24


# Do not configure CLK as Pin.OUT; PIO must own that pin. DATA stays a normal input.
_data = Pin(PDM_DATA_GPIO, Pin.IN)
_clk = Pin(PDM_CLK_GPIO)

_sm = rp2.StateMachine(
    0,
    pdm_bit_capture,
    freq=_SM_FREQ,
    in_base=_data,
    set_base=_clk,
)
# Do not start here: until main() runs, a running SM would fill the tiny RX FIFO
# (4 words) and stall — bad for the mic clock. Started explicitly in main().


def drain_pdm_bitcount(n_words):
    """Pull n_words 32-bit words from PIO; return (ones_count, total_bits)."""
    ones = 0
    for _ in range(n_words):
        while _sm.rx_fifo() == 0:
            pass
        ones += _popcount_u32(_sm.get())
    return ones, 32 * n_words


def _drain_words_discard(n_words):
    """Pull n_words from FIFO and throw them away (warm-up / flush)."""
    for _ in range(n_words):
        while _sm.rx_fifo() == 0:
            pass
        _sm.get()


def _flush_rx_fifo():
    while _sm.rx_fifo():
        _sm.get()


def main():
    # RX FIFO is only 4 entries deep on RP2040/2350 PIO — if we sleep while the SM
    # keeps running, the FIFO fills, the SM stalls, the PDM clock to the mic stops,
    # and the next block is nonsense → wild 0..100 swings. So: stop SM, sleep,
    # restart, discard warm-up words, then measure.
    n_words = 800
    dc = 0.5
    dc_alpha = 0.02
    loud_smooth = None

    while True:
        _sm.active(1)
        _drain_words_discard(128)
        ones, bits = drain_pdm_bitcount(n_words)
        density = ones / bits

        dc = (1.0 - dc_alpha) * dc + dc_alpha * density
        ac = density - dc
        level = abs(ac)
        instant = min(100, round(level * _LOUDNESS_SCALE))
        if loud_smooth is None:
            loud_smooth = float(instant)
        else:
            loud_smooth = _LOUDNESS_SMOOTH * loud_smooth + (1.0 - _LOUDNESS_SMOOTH) * instant

        print(
            "density={:.4f}  loudness={}/100".format(density, int(round(loud_smooth)))
        )

        _flush_rx_fifo()
        _sm.active(0)
        time.sleep_ms(200)


if __name__ == "__main__":
    main()
