"""
pdm_fft_analysis.py

Reads a TXT file containing PDM bits (0s and 1s),
converts to a PCM-like waveform using a moving average low-pass filter,
plots the waveform,
computes FFT,
finds the dominant frequency,
and plots the frequency spectrum.

Usage:
    python pdm_fft_analysis.py data.txt
"""

import sys
import numpy as np
import matplotlib.pyplot as plt



PDM_SAMPLE_RATE = 1_000_000   # Hz (change to to actual PDM clock rate)
DECIMATION = 64               # moving average window size
PLOT_SAMPLES = 5000           # waveform samples to display


# LOAD PDM DATA

if len(sys.argv) < 2:
    print("Usage: python pdm_fft_analysis.py data.txt")
    sys.exit(1)

filename = sys.argv[1]

with open(filename, "r") as f:
    text = f.read()

# keep only 0 and 1 characters
bits = [int(c) for c in text if c in ('0', '1')]

if len(bits) == 0:
    raise ValueError("No valid PDM bits found.")

pdm = np.array(bits, dtype=np.float32)

print(f"Loaded {len(pdm)} PDM bits")


# PDM -> PCM CONVERSION

# convert 0/1 to -1/+1
pdm_signed = 2 * pdm - 1

# simple low-pass filter using moving average
kernel = np.ones(DECIMATION) / DECIMATION
pcm = np.convolve(pdm_signed, kernel, mode='valid')

# decimate
pcm = pcm[::DECIMATION]

pcm_sample_rate = PDM_SAMPLE_RATE / DECIMATION

print(f"PCM sample rate: {pcm_sample_rate:.1f} Hz")
print(f"PCM samples: {len(pcm)}")


# PLOT WAVEFORM

plt.figure(figsize=(12, 5))

samples_to_show = min(PLOT_SAMPLES, len(pcm))
time_axis = np.arange(samples_to_show) / pcm_sample_rate

plt.plot(time_axis, pcm[:samples_to_show])

plt.title("Recovered PCM Waveform")
plt.xlabel("Time (s)")
plt.ylabel("Amplitude")
plt.grid(True)

plt.tight_layout()
plt.show()


# FFT ANALYSIS

N = len(pcm)

# remove DC offset
pcm_centered = pcm - np.mean(pcm)

# apply window
window = np.hanning(N)
windowed = pcm_centered * window

# FFT
fft_vals = np.fft.rfft(windowed)
fft_freqs = np.fft.rfftfreq(N, d=1/pcm_sample_rate)

# magnitude
magnitude = np.abs(fft_vals)

# ignore DC component
magnitude[0] = 0

# dominant frequency
peak_index = np.argmax(magnitude)
dominant_freq = fft_freqs[peak_index]

print(f"\nDominant Frequency: {dominant_freq:.2f} Hz")


# PLOT FFT

plt.figure(figsize=(12, 5))

plt.plot(fft_freqs, magnitude)

plt.title("FFT Spectrum")
plt.xlabel("Frequency (Hz)")
plt.ylabel("Magnitude")
plt.grid(True)

plt.xlim(0, pcm_sample_rate / 2)

plt.tight_layout()
plt.show()