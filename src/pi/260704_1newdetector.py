# pi4_detector.py - reads the PCM stream from the Pico over USB serial,
# runs a sliding-window FFT, and flags energy in the 20-59kHz bat-call band.
#
# install deps:
#   pip3 install pyserial numpy
#
# run this fileee

import serial            # talks to the Pico's USB-CDC serial port
import numpy as np       # FFT + array math
import time               # timestamps and cooldown timing
import sys                # sys.exit() on config error

PORT = "/dev/ttyACM0"           # Linux device node for the Pico's virtual serial port
SAMPLE_RATE = 192000             # must match CIC_DECIM setup on the Pico (3.072MHz / 16)

WINDOW_SIZE = 2048               # samples per FFT window (~10.7ms at 192kHz)
HOP_SIZE = 1024                  # samples between windows (50% overlap)

BAND_LO_HZ = 20_000              # lower edge of the bat-call band of interest
BAND_HI_HZ = 59_000              # upper edge of the bat-call band of interest

# detection threshold - TUNE THIS manually(!!) once data is flowing.
# this is comparing FFT bin magnitude, not raw amplitude, so start low,
# watch the printed magnitudes during quiet vs. noisy periods, and set
# it above the quiet-room noise floor.
THRESHOLD = 5000                 # magnitude above which a bin counts as "a call"

# cooldown so one call doesn't spam dozens of detections
DETECTION_COOLDOWN_S = 0.3       # minimum seconds between two printed detections

# how often to print raw PCM values (for debugging/inspection)
RAW_PRINT_INTERVAL_S = 1.0       # print raw ints at most once per second


def open_serial():
    print(f"opening {PORT} ...")
    # open the port; timeout=1 means read() calls give up (return what they have,
    # possibly empty) after 1s rather than blocking forever
    ser = serial.Serial(PORT, baudrate=115200, timeout=1)
    # baudrate is ignored over USB CDC (it's full-speed USB underneath),
    # but pyserial requires you pass something.
    return ser


def read_exact(ser, n_bytes):
    """Read exactly n_bytes, handling partial USB reads."""
    buf = bytearray()                    # accumulates bytes until we have enough
    while len(buf) < n_bytes:            # keep reading until the request is satisfied
        chunk = ser.read(n_bytes - len(buf))   # ask for the remaining bytes
        if not chunk:                    # timeout with nothing read -> just retry
            continue
        buf.extend(chunk)                # append whatever partial chunk arrived
    return bytes(buf)                    # return an immutable bytes object


def main():
    ser = open_serial()                  # open the connection to the Pico

    # precompute FFT bin -> frequency mapping and the band mask
    freqs = np.fft.rfftfreq(WINDOW_SIZE, d=1.0 / SAMPLE_RATE)  # frequency (Hz) of each rFFT bin
    band_mask = (freqs >= BAND_LO_HZ) & (freqs <= BAND_HI_HZ)  # boolean mask selecting bat-band bins
    band_freqs = freqs[band_mask]        # the actual frequency values inside the band

    if not np.any(band_mask):            # sanity check: does the band fall within the FFT resolution?
        print("ERROR: no FFT bins fall in the target band at this "
              "SAMPLE_RATE/WINDOW_SIZE - increase WINDOW_SIZE.")
        sys.exit(1)                      # abort — nothing useful can be detected otherwise

    window_fn = np.hanning(WINDOW_SIZE)  # Hann window to reduce spectral leakage before FFT

    # rolling sample buffer
    sample_buf = np.zeros(WINDOW_SIZE, dtype=np.float32)  # holds the most recent WINDOW_SIZE samples
    bytes_per_hop = HOP_SIZE * 2         # int16 = 2 bytes, so this many bytes arrive per hop

    last_detection_time = 0.0            # monotonic timestamp of the last printed detection
    last_raw_print_time = 0.0            # monotonic timestamp of the last raw-PCM print

    print(f"listening for {BAND_LO_HZ/1000:.0f}-{BAND_HI_HZ/1000:.0f}kHz "
          f"activity (threshold={THRESHOLD}) ...")

    # prime the buffer with a full window first
    raw = read_exact(ser, WINDOW_SIZE * 2)                       # read WINDOW_SIZE int16 samples (2 bytes each)
    sample_buf[:] = np.frombuffer(raw, dtype='<i2').astype(np.float32)  # decode little-endian int16 -> float32

    while True:
        # slide the buffer by HOP_SIZE and read in the new samples
        raw = read_exact(ser, bytes_per_hop)                     # block until the next hop's worth of bytes arrive
        new_samples_i16 = np.frombuffer(raw, dtype='<i2')        # decode the new chunk as raw int16 samples
        new_samples = new_samples_i16.astype(np.float32)         # float32 copy for FFT math

        now = time.monotonic()                                   # current time, reused below for raw-print throttling
        if (now - last_raw_print_time) > RAW_PRINT_INTERVAL_S:
            # print raw PCM ints at most once per second, so the terminal isn't a firehose
            last_raw_print_time = now
            uniq = np.unique(new_samples_i16)                    # distinct values in this hop
            print(f"[{time.strftime('%H:%M:%S')}] raw PCM: "
                  f"min={new_samples_i16.min()} max={new_samples_i16.max()} "
                  f"mean={new_samples_i16.mean():.1f} unique_count={uniq.size} "
                  f"first20={new_samples_i16[:20].tolist()}")

        sample_buf = np.roll(sample_buf, -HOP_SIZE)              # shift buffer left, dropping the oldest HOP_SIZE samples
        sample_buf[-HOP_SIZE:] = new_samples                     # fill the freed tail with the newly read samples

        spectrum = np.fft.rfft(sample_buf * window_fn)           # windowed real FFT of the current buffer
        magnitude = np.abs(spectrum)                             # magnitude spectrum (drop phase info)

        band_mag = magnitude[band_mask]                          # magnitudes restricted to the bat-call band
        peak_idx = np.argmax(band_mag)                           # index of the strongest bin within the band
        peak_mag = band_mag[peak_idx]                            # its magnitude
        peak_freq = band_freqs[peak_idx]                         # its corresponding frequency

        if peak_mag > THRESHOLD and (now - last_detection_time) > DETECTION_COOLDOWN_S:
            # peak exceeds threshold AND we're past the cooldown window -> report a detection
            last_detection_time = now                            # reset cooldown clock
            print(f"[{time.strftime('%H:%M:%S')}] call detected: "
                  f"~{peak_freq/1000:.1f}kHz  (magnitude {peak_mag:.0f})")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:            # let Ctrl+C exit cleanly instead of a traceback
        print("\nstopped")