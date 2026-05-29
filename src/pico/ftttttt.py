
import numpy as np
import matplotlib.pyplot as plt

filename = "/Users/tasneemsalek/Downloads/wildlife_monitoring_utwind/src/pico/raww.txt"  
Fs = 2000000               # sampling rate in Hz, {NEEDS TO BE CHANGEDDDDDD}

# one number per line
x = np.loadtxt(filename)

x = x - np.mean(x)

window = np.hanning(len(x))
x = x * window

fft_vals = np.fft.rfft(x)

# frequency axis
freqs = np.fft.rfftfreq(len(x), d=1/Fs)

# magnitude spectrum
magnitude = np.abs(fft_vals)

# ignore DC component
magnitude[0] = 0

peak_index = np.argmax(magnitude)
peak_freq = freqs[peak_index]

print(f"Peak frequency: {peak_freq:.2f} Hz")

plt.figure(figsize=(10,5))
plt.plot(freqs, magnitude)
plt.xlabel("Frequency (Hz)")
plt.ylabel("Magnitude")
plt.title("FFT Spectrum, ")
plt.grid(True)
plt.show()