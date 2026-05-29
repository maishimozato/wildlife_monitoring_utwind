import rp2
from machine import Pin
import time

PDM_CLK = 2
PDM_DATA = 3

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

WINDOW = 64          # PDM bits per PCM sample
PCM_SAMPLES = 400    # total PCM samples, temporary

while True:

    pcm = []

    # Build PCM waveform
    for _ in range(PCM_SAMPLES):

        count = 0

        for _ in range(WINDOW):
            count += data.value()

        sample = count - (WINDOW // 2)

        pcm.append(sample)

    # zero crossing frequency ESTIMATEEEE
    crossings = 0

    for i in range(1, len(pcm)):
        if pcm[i-1] < 0 and pcm[i] >= 0:
            crossings += 1

    # sample rate
    sample_rate = 1000000 / WINDOW

    frequency = (crossings * sample_rate) / len(pcm)

    print("Freq:", int(frequency), "Hz")

    time.sleep(0.1)