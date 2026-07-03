# pi4_detector.py - reads the PCM stream from the Pico over USB serial,
# runs a sliding-window FFT, and flags energy in the 20-59kHz bat-call band.
#
# install deps:
#   pip3 install pyserial numpy
#
# run this fileee
#
# matches the pico firmware's output: raw little-endian int16 PCM,
# no framing/header, at SAMPLE_RATE.

import serial
import numpy as np
import time
import sys

PORT = "/dev/ttyACM0"
SAMPLE_RATE = 192000        # must match CIC_DECIM setup on the Pico (3.072MHz / 16)

WINDOW_SIZE = 2048          # samples per FFT window (~10.7ms at 192kHz)
HOP_SIZE = 1024              # samples between windows (50% overlap)

BAND_LO_HZ = 20_000
BAND_HI_HZ = 59_000

# detection threshold - TUNE THIS manually(!!) once data is flowing.
# this is comparing FFT bin magnitude, not raw amplitude, so start low,
# watch the printed magnitudes during quiet vs. noisy periods, and set
# it above the quiet-room noise floor.
THRESHOLD = 5000

# cooldown so one call doesn't spam dozens of detections
DETECTION_COOLDOWN_S = 0.3


def open_serial():
    print(f"opening {PORT} ...")
    ser = serial.Serial(PORT, baudrate=115200, timeout=1)
    # baudrate is ignored over USB CDC (it's full-speed USB underneath),
    # but pyserial requires you pass something.
    return ser


def read_exact(ser, n_bytes):
    """Read exactly n_bytes, handling partial USB reads."""
    buf = bytearray()
    while len(buf) < n_bytes:
        chunk = ser.read(n_bytes - len(buf))
        if not chunk:
            continue
        buf.extend(chunk)
    return bytes(buf)


def main():
    ser = open_serial()

    # precompute FFT bin -> frequency mapping and the band mask
    freqs = np.fft.rfftfreq(WINDOW_SIZE, d=1.0 / SAMPLE_RATE)
    band_mask = (freqs >= BAND_LO_HZ) & (freqs <= BAND_HI_HZ)
    band_freqs = freqs[band_mask]

    if not np.any(band_mask):
        print("ERROR: no FFT bins fall in the target band at this "
              "SAMPLE_RATE/WINDOW_SIZE - increase WINDOW_SIZE.")
        sys.exit(1)

    window_fn = np.hanning(WINDOW_SIZE)

    # rolling sample buffer
    sample_buf = np.zeros(WINDOW_SIZE, dtype=np.float32)
    bytes_per_hop = HOP_SIZE * 2  # int16 = 2 bytes

    last_detection_time = 0.0

    print(f"listening for {BAND_LO_HZ/1000:.0f}-{BAND_HI_HZ/1000:.0f}kHz "
          f"activity (threshold={THRESHOLD}) ...")

    # prime the buffer with a full window first
    raw = read_exact(ser, WINDOW_SIZE * 2)
    sample_buf[:] = np.frombuffer(raw, dtype='<i2').astype(np.float32)

    while True:
        # slide the buffer by HOP_SIZE and read in the new samples
        raw = read_exact(ser, bytes_per_hop)
        new_samples = np.frombuffer(raw, dtype='<i2').astype(np.float32)

        sample_buf = np.roll(sample_buf, -HOP_SIZE)
        sample_buf[-HOP_SIZE:] = new_samples

        spectrum = np.fft.rfft(sample_buf * window_fn)
        magnitude = np.abs(spectrum)

        band_mag = magnitude[band_mask]
        peak_idx = np.argmax(band_mag)
        peak_mag = band_mag[peak_idx]
        peak_freq = band_freqs[peak_idx]

        now = time.monotonic()
        if peak_mag > THRESHOLD and (now - last_detection_time) > DETECTION_COOLDOWN_S:
            last_detection_time = now
            print(f"[{time.strftime('%H:%M:%S')}] call detected: "
                  f"~{peak_freq/1000:.1f}kHz  (magnitude {peak_mag:.0f})")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nstopped")