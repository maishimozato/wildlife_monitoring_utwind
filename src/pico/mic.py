from machine import I2S, Pin
import array
import time

# I2S pins
sck_pin = Pin(2)    # BCLK
ws_pin = Pin(3)     # LRCLK
sd_pin = Pin(4)     # DATA

audio = I2S(
    0,
    sck=sck_pin,
    ws=ws_pin,
    sd=sd_pin,
    mode=I2S.RX,
    bits=32,
    format=I2S.MONO,
    rate=16000,
    ibuf=4000
)

buf = bytearray(1024)

while True:
    audio.readinto(buf)

    # Convert 32-bit samples to signed values
    samples = array.array("i", buf)

    level = 0
    for s in samples:
        level += abs(s)

    level //= len(samples)
    print("Volume:", level)
    time.sleep(0.1)
