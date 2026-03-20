import rp2
from machine import Pin
import time
import math

PDM_CLK = 2
PDM_DATA = 3

clk = Pin(PDM_CLK, Pin.OUT)
data = Pin(PDM_DATA, Pin.IN)

# PIO: generate clock + accumulate bits
@rp2.asm_pio(
    set_init=rp2.PIO.OUT_LOW,
    autopush=True,
    push_thresh=32
)
def pdm_sum():
    wrap_target()

    # read bit
    in_(pins, 1)

    # clock high
    set(pins, 1)
    # clock low
    set(pins, 0)

    wrap()

# start PIO
sm = rp2.StateMachine(
    0,
    pdm_sum,
    freq=2000000,     # 2 MHz clock
    in_base=data,
    set_base=clk
)

sm.active(1)

# apparently fast bit count
def popcount(x):
    return bin(x).count("1")

# main loop
while True:

    total_ones = 0
    total_bits = 0

    # read a bunch of PDM data
    for _ in range(500):
        while sm.rx_fifo() == 0:
            pass

        val = sm.get()
        total_ones += popcount(val)
        total_bits += 32

    # normalize?
    level = total_ones / total_bits

    # convert to amplitude (center at 0)
    amplitude = abs(level - 0.5)

    # convert to relative dB
    db = 20 * math.log10(amplitude + 1e-6)

    print("Level:", level, "Amp:", amplitude, "dB:", db)

    time.sleep(0.1)