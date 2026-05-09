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

try:
    while True:                                                     # infinite loop!! (Ctrl+C to stop)
        count = 0                                                   # counter variable
        samples = 10000

        for _ in range(samples):                                    # loops 10000 times
            count += data.value()                                   # reads digital value on the data pin (0 or 1), then adds it, {6}

        level = count / samples                                     # fraction of ones {6}
        levels.append(level)                                        # remember it for later plotting

        deviation = abs(level - 0.5)*800
        bars = int(deviation)

        #print("level:", level, " deviation:", deviation)
        print(bars*"#")

        time.sleep(0.2)

except KeyboardInterrupt:
    # Save every level we collected to a file on the Pico, one float per line.
    # The Pico cannot plot (no matplotlib), so we save and plot on the laptop later. {9}
    print("\n[stopping] saving", len(levels), "levels to", LEVELS_FILE)
    with open(LEVELS_FILE, "w") as f:
        for v in levels:
            f.write("{}\n".format(v))
    print("[done] copy it off with:  mpremote cp :levels.txt .")


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
{5}     execution freq = 2MHz, loop has 2 instructions → clock frequency = 1MHz
{6}     counts how many 1 bits happened in sample window, for example:
        samples = 10000, count = 5000 → ones 50% of the time
{7}     each loop appends one float to `levels`. After many loops you have a
        time-series of "fraction of 1 bits per window" -> good enough to plot a
        slow envelope of activity (NOT the audio waveform itself).
{8}     /levels.txt is on the Pico's internal flash filesystem. Survives reset.
        Get it back with:   mpremote cp :levels.txt .
{9}     MicroPython on Pico has no matplotlib / no GUI. Plotting must happen on
        a normal computer. So: collect on Pico, save file, copy off, plot on laptop.
"""
