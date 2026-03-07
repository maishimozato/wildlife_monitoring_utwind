import rp2                                #RP2040 PIO
from machine import Pin
import time

# pins
PDM_CLK = 2
PDM_DATA = 3

# set up clock pin input/output 
clk = Pin(PDM_CLK, Pin.OUT)
data = Pin(PDM_DATA, Pin.IN)

# simple PDM clock generator (around 1 MHz)
@rp2.asm_pio(set_init=rp2.PIO.OUT_LOW)
def pdm_clock():
    wrap_target()
    set(pins, 1)                          #clkpin high
    set(pins, 0)                          #clkpin low?
    wrap()                                #loop foreverrr --> wrap_target

# load PIO
sm = rp2.StateMachine(0, pdm_clock, freq=2000000, set_base=clk)
sm.active(1)

# simple sound level detector
while True:
    count = 0
    samples = 10000

    for _ in range(samples):
        count += data.value()

    level = count / samples

    print("Sound level:", level)
    time.sleep(0.2)
