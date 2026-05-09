# SPH0641LU4H-1 on Pico 2: CLK=GPIO2, DATA=GPIO3, SEL=GND, VDD=3V3.
# Stock MicroPython does not expose the RP2040/RP2350 PDM peripheral, so this
# uses PIO to (1) drive the mic clock and (2) sample DATA once per clock bit,
# in lockstep — unlike polling Pin.value() in Python, which is meaningless for PDM.

"""
checks deviation from 0.5
"""

import rp2                                                          # import RP2040 PIO library!!, [1]
from machine import Pin                                             # to control gpio pins on the pico             
import time                                                         # we need time funcitons so...

# pins, numbers 2 and 3 represent the pin no. where the mics clock and data are connected
PDM_CLK = 2                                                         # declared as variables for debugging(?) purposes                                
PDM_DATA = 3                                                        # + in case we decide to rewire this thing

# DATA = normal input. CLK = leave alone here; PIO must OWN that pin (no Pin.OUT!), see {7}
clk = Pin(PDM_CLK)
data = Pin(PDM_DATA, Pin.IN)

# Datasheet says mic CLK should be ~1.024–2.475 MHz. Our PIO loop runs 3 instructions
# per full clock cycle (in_, set high, set low), so SM_FREQ = 3 * desired_CLK.  See {5}
PDM_CLK_HZ = 2_400_000
SM_FREQ    = PDM_CLK_HZ * 3

# PIO program: drives CLK AND samples DATA on every clock bit, in lockstep, see {8}
@rp2.asm_pio(
    set_init=rp2.PIO.OUT_LOW,                                       # CLK pin starts low, [2]
    autopush=True,                                                  # auto-push ISR into RX FIFO when full, see {9}
    push_thresh=32,                                                 # ...every 32 bits → one 32-bit word per push
)
def pdm_clock():                                                    # actually clock + capture now, not just clock
    wrap_target()                                                   # starts a loop
    in_(pins, 1)                                                    # latch 1 DATA bit into ISR  ← THIS is the "don't miss data" line
    set(pins, 1)                                                    # CLK high, {3}
    set(pins, 0)                                                    # CLK low,  {3}
    wrap()                                                          # loop!

# in_base tells PIO which pin `in_(pins, 1)` reads from (DATA).  set_base is the CLK pin.
sm = rp2.StateMachine(
    0, pdm_clock,
    freq=SM_FREQ,
    in_base=data,
    set_base=clk,
)


def popcount32(x):                                                  # counts 1-bits in a 32-bit word, see {10}
    x &= 0xFFFFFFFF
    x = x - ((x >> 1) & 0x55555555)
    x = (x & 0x33333333) + ((x >> 2) & 0x33333333)
    x = (x + (x >> 4)) & 0x0F0F0F0F
    return ((x * 0x01010101) & 0xFFFFFFFF) >> 24


# simple sound level detector
while True:                                                         # infinite loop!!
    # RX FIFO is only 4 words deep. If SM keeps running while we sleep, FIFO fills,
    # SM stalls, mic clock stops → next read is garbage. So: start, capture, stop, sleep. {11}
    sm.active(1)

    # warm-up: throw away the first few words while things settle
    for _ in range(8):
        while sm.rx_fifo() == 0:
            pass
        sm.get()

    # actual capture: every word = 32 PDM bits, none missed (PIO grabbed each one)
    n_words = 320                                                   # 320 * 32 = 10240 bits ≈ old "samples = 10000"
    ones = 0
    for _ in range(n_words):
        while sm.rx_fifo() == 0:                                    # wait until PIO has pushed a word
            pass
        ones += popcount32(sm.get())                                # pull word, count its 1-bits, {6}

    # drain leftovers and pause SM so it doesn't stall during sleep
    while sm.rx_fifo():
        sm.get()
    sm.active(0)

    bits = n_words * 32
    level = ones / bits                                             # fraction of ones {6}

    deviation = abs(level - 0.5) * 800
    bars = int(deviation)

    #print("level:", level, " deviation:", deviation)
    print(bars * "#")

    time.sleep(0.2)


"""
ABBREVIATIONS(?)
PIO : programmable input output
CLK : clock


LINKS

[1]:    https://docs.micropython.org/en/latest/rp2/quickref.html
[2]:    https://www.digikey.ca/en/maker/projects/raspberry-pi-pico-and-rp2040-micropython-part-3-pio/3079f9f9522743d09bb65997642e0831

[3]:    https://medium.com/geekculture/raspberry-pico-programming-with-pio-state-machines-e4610e6b0f29


EXPLANATIONS

{1}     we need a clock so that the mic knows when to sample, how fast bits are genenrated
{2}     apparently the mic sends 1 bit digital stream
{3}     square wave clocks alternate bw high and low (HIGH → LOW → HIGH → LOW)
{4}     pico has mini processors(?) called state machines that handle pins, see [3]
{5}     execution freq is in PIO instructions/sec. Our loop has 3 instructions per
        full clock cycle, so CLK_freq = SM_freq / 3.  e.g. 7.2 MHz / 3 = 2.4 MHz CLK.
{6}     counts how many 1 bits happened in sample window, for example:
        samples = 10000, count = 5000 → ones 50% of the time
{7}     if you Pin.OUT a pin AND let PIO drive it via set_base, they fight.
        PIO must own the clock pin alone.
{8}     "lockstep" = each DATA bit is read inside the same loop iteration that
        pulses the CLK, so we always sample exactly when the mic is presenting a bit.
{9}     ISR = Input Shift Register inside the PIO. autopush dumps it into the
        RX FIFO automatically when push_thresh bits have been shifted in.
{10}    "popcount" / Hamming weight: bit-twiddling trick to count 1-bits in a
        32-bit number much faster than a Python for-loop over each bit.
{11}    RX FIFO depth = 4 words. Sleeping with SM running will overfill it,
        stall the state machine, and freeze the mic clock → bad data next round.
"""
