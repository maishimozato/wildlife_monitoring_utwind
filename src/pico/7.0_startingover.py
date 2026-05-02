import rp2                                                          
from machine import Pin                                                          
import time

PDM_CLK = 2
PDM_DATA =3

clk = Pin(PDM_CLK, Pin.OUT)
data = Pin(PDM_DATA, Pin.IN)

@rp2.asm_pio(set_init=rp2.PIO.OUT_LOW)
def pdm_clock():
    wrap_target()
    set(pins, 1)
    set(pins, 0)
    wrap()
    
sm = rp2.StateMachine(0, pdm_clock, freq=2000000, set_base=clk)
sm.active(1)

while True:
    count = 0
    samples = 10000
    
    for _ in range(samples):
        count += data.value()
    
    level = count / samples
    print("Sound level:", level)
    time.sleep(0.2)