import rp2                                  # import RP2040 PIO library!!
from machine import Pin                     # to control gpio pins on the pico             
import time                                 # we need time funcitons so...

# pins, numbers 2 and 3 represent the pin no. where the mics clock and data are connected
PDM_CLK = 2                                 # declared as variables for debugging(?) purposes                                
PDM_DATA = 3                                # + in case we decide to rewire this thing

# set up clock pin input/output 
clk = Pin(PDM_CLK, Pin.OUT)                 # the mic doesnt make its clock, so the pico has to send clocl to mic 
data = Pin(PDM_DATA, Pin.IN)                # self-explanatory; pico gets the data from mic as input

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
