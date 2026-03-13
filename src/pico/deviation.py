"""
code to test if microphone works (part 2)

[x] = links/references
{x} = explanations

see end of file for more!!
"""

import rp2
import time
from machine import Pin

data = Pin(3, Pin.IN)

while True:
    samples = 10000
    count = 0

    for _ in range(samples):
        count += data.value()

    level = count / samples
    deviation = abs(level - 0.5)

    print("level:", level, " deviation:", deviation)

    time.sleep(0.2)