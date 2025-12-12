import numpy as np
import matplotlib.pyplot as plt

# parameters!!
fs = 192000  # Sampling frequency (192 kHz, high enough for 40 kHz signal)
duration = 0.005  # 5 ms duration
f_signal = 40000  # 40 kHz sine wave

# generate time axis
t = np.linspace(0, duration, int(fs * duration), endpoint=False)

# generate 40 kHz sine wave
signal = np.sin(2 * np.pi * f_signal * t)

# compute FFT
N = len(signal)
fft_vals = np.fft.fft(signal) #converts the time-domain signal into its frequency components
fft_freq = np.fft.fftfreq(N, 1/fs)

# use only the positive frequencies
mask = fft_freq >= 0
fft_freq = fft_freq[mask]
fft_vals = np.abs(fft_vals[mask])

# plot time domain signal; signal vs time
plt.figure()
plt.plot(t[:500], signal[:500])  # show only first 500 samples for clarity
plt.title("time domain (40 kHz sin wave)")
plt.xlabel("time (s)")
plt.ylabel("amplitude")
plt.show()

# plot frequency domain spectrum; magnitude vs frequency
plt.figure()
plt.plot(fft_freq, fft_vals)
plt.title("frequency domain (FFT spectrum)")
plt.xlabel("frequency (Hz)")
plt.ylabel("magnitude")
plt.xlim(0, 90000)
plt.show()