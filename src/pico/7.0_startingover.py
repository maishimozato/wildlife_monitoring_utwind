# SPH0641LU4H-1 on Pico 2: CLK=GPIO2, DATA=GPIO3, SEL=GND, VDD=3V3.
#
# Stock MicroPython does not expose the RP2040/RP2350 PDM peripheral, so this
# uses PIO to (1) drive the mic clock and (2) sample DATA once per clock bit,
# in lockstep — unlike polling Pin.value() in Python, which is meaningless for PDM.
#
# Output is a practical loudness proxy (high-passed bit density), not broadcast PCM.
# For real audio, use a C SDK / OpenPDM2PCM-style pipeline or a firmware with PDM RX.

import math
import time

import rp2
from machine import Pin

PDM_CLK_GPIO = 2
PDM_DATA_GPIO = 3

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
_sm.active(1)


def drain_pdm_bitcount(n_words):
    """Pull n_words 32-bit words from PIO; return (ones_count, total_bits). No big list."""
    ones = 0
    for _ in range(n_words):
        while _sm.rx_fifo() == 0:
            pass
        ones += _popcount_u32(_sm.get())
    return ones, 32 * n_words


def main():
    # Longer blocks → smoother level; keep read loop tight to avoid RX FIFO overflow.
    n_words = 400
    dc = 0.5
    dc_alpha = 0.02

    while True:
        ones, bits = drain_pdm_bitcount(n_words)
        density = ones / bits

        # PDM: silence sits near 0.5 density; slow DC tracker removes offset drift.
        dc = (1.0 - dc_alpha) * dc + dc_alpha * density
        ac = density - dc
        # Cheap loudness proxy (not SPL); log avoids -inf when perfectly quiet.
        level = abs(ac)
        db = 20.0 * math.log10(level + 1e-9)

        print(
            "PDM_clk~{}MHz density={:.4f} hp={:.5f} level={:.5f} dB_est={:.1f}".format(
                _PDM_CLK_HZ / 1e6,
                density,
                ac,
                level,
                db,
            )
        )
        time.sleep_ms(200)


if __name__ == "__main__":
    main()
