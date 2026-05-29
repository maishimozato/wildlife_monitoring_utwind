"""
checks deviation from 0.5
"""

import rp2                                                          # import RP2040 PIO library!!, [1]
from machine import Pin                                             # to control gpio pins on the pico             
import time                                                         # we need time funcitons so...

# pins, numbers 2 and 3 represent the pin no. where the mics clock and data are connected
PDM_CLK = 2                                                         # declared as variables for debugging(?) purposes                                
PDM_DATA = 3                                                        # + in case we decide to rewire this thing

# set up clock pin input/output 
clk = Pin(PDM_CLK, Pin.OUT)                                         # the mic doesnt make its own clock, so the pico has to send clocl to mic, also see {1} 
data = Pin(PDM_DATA, Pin.IN)                                        # self-explanatory; pico gets the data from mic as input, see {2}

# simple PDM clock generator (around 1 MHz), see {1}
@rp2.asm_pio(set_init=rp2.PIO.OUT_LOW)                              # see [2], initializes low pin output at beginning
def pdm_clock():                                                    # will generate a high speed square wave clock, see {3}
    wrap_target()                                                   # starts a loop
    set(pins, 1)                                                    # clkpin high, {3}
    set(pins, 0)                                                    # clkpin low, {3}
    wrap()                                                          # returns to line 25, loop!

# ??? 
sm = rp2.StateMachine(0, pdm_clock, freq=2000000, set_base=clk)     # creates a pio state machine to run pio program, see {4}, {5}
sm.active(1)                                                        # turns the machine on

# simple sound level detector
levels = []                                                         # remember every level value, so we can save them at the end, see {7}
LEVELS_FILE = "/levels.txt"                                         # where to dump the recording on the Pico's flash, {8}

rawdata = []
DATA_FILE = "/data.txt"


try:
    while True:                                                     # infinite loop!! (Ctrl+C to stop)
        count = 0                                                   # counter variable
        samples = 10000

        for _ in range(samples):                                    # loops 10000 times
            count += data.value()                                   # reads digital value on the data pin (0 or 1), then adds it, {6}


        raw = data.value()
        rawdata.append(raw)

        level = count / samples                                     # fraction of ones {6}
        levels.append(level)                                        # remember it for later plotting

        deviation = abs(level - 0.5)*800
        bars = int(deviation)

        print("level:", level, " deviation:", deviation)
        #print(bars*"#")

        time.sleep(0.2)

except KeyboardInterrupt:
    
    print("\n[stopping] saving", len(levels), "levels to", LEVELS_FILE)
    with open(LEVELS_FILE, "w") as f:
        for v in levels:
            f.write("{}\n".format(v))
    print("[done] copy it off with:  mpremote cp :levels.txt .")

    print("\n[stopping] saving", len(levels), "levels to", DATA_FILE)
    with open(DATA_FILE, "w") as f:
        for v in rawdata:
            f.write("{}\n".format(v))
    print("[done] copy it off with:  mpremote cp :data.txt .")


