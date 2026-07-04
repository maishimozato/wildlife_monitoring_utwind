"""
bat_detection.py
================

Integrated wildlife deterrent for the Pi 4.

Triggers the speaker when BOTH conditions are met at nearly the same time:
  1) A bat call is detected in the 20-59 kHz band
     (via PCM stream from the Pico over USB + sliding-window FFT)
  2) The LiDAR reports an object closer than DIST_TRIGGER_CM
     (via TFmini on /dev/serial0)

Bat detection = a >FFT_THRESHOLD peak in the 20-59 kHz band of the PCM stream
that the Pico is sending over USB (see 260703_sendtopi4.py).

Distance = TFmini-family LiDAR on /dev/serial0.

Prototype note: RANGE_CM is 100 cm here for testing. In the real deployment
this would be much larger (e.g. 20000 cm ≈ 200 m).

Prereqs on the Pi:
  pip install pyserial numpy
  # UART enabled via raspi-config, user in dialout group.
  # GPIO 18 sysfs access usually requires either sudo or the 'gpio' group.

Run:
  sudo /home/admin/.venv/bin/python bat_detection.py
"""

import glob
import os
import sys
import time
import threading

try:
    import serial
    import numpy as np
except ImportError as e:
    print(f"ERROR: missing dependency: {e}", file=sys.stderr)
    print("Fix:   pip install pyserial numpy", file=sys.stderr)
    sys.exit(1)


# =============================================================================
# Config (tune these)
# =============================================================================

# Pico (bat mic PCM stream) — USB CDC device
PICO_PORT = "/dev/ttyACM0"
PICO_BAUD = 115200                 # ignored over USB CDC; pyserial still needs a value

# LiDAR (TFmini-family) — UART on GPIO header
LIDAR_PORT = "/dev/serial0"
LIDAR_BAUD = 115200

# Bat FFT settings — must match Pico firmware output rate
SAMPLE_RATE = 192_000              # samples/s of the PCM stream from the Pico
WINDOW_SIZE = 2048                 # samples per FFT (~10.7 ms at 192 kHz)
HOP_SIZE = 1024                    # 50% overlap
BAND_LO_HZ = 20_000                # bat-call frequency band
BAND_HI_HZ = 59_000
FFT_THRESHOLD = 5000               # bin magnitude threshold — TUNE against room noise

# Distance zones (match speaker4.py)
RANGE_CM = 100                     # object closer than this → start beeping (if bat hot)
SOLID_CM = 15                      # object closer than this → near-solid alarm

# Parking-sensor tone shape (match speaker4.py)
BEEP_DURATION_S = 0.12             # length of each individual beep
BEEP_FREQ_NEAR = 1600              # Hz at 0 cm (highest)
BEEP_FREQ_FAR  = 800               # Hz at RANGE_CM (lowest)
BEEP_PERIOD_NEAR = 0.15            # gap between beeps at 0 cm (fastest)
BEEP_PERIOD_FAR  = 1.00            # gap between beeps at RANGE_CM (slowest)

# Solid-alarm mode (dist < SOLID_CM)
SOLID_DURATION_S = 0.25
SOLID_FREQ = 1600

# Bat "recently heard" window — how long a detection stays hot for gating beeps
COINCIDENCE_WINDOW_S = 2.0

# Speaker (BCM GPIO 18, header pin 12) via sysfs — matches speaker4.py
SPEAKER_BCM = 18


def _sysfs_pin_number(bcm):
    """On kernel 6.6+ the sysfs base moved off zero (Pi 4 uses base 512), so
    the sysfs pin = base + BCM. Older kernels had base=0. Discover at runtime."""
    for chip in glob.glob("/sys/class/gpio/gpiochip*"):
        try:
            with open(f"{chip}/label") as f:
                label = f.read().strip().lower()
            with open(f"{chip}/base") as f:
                base = int(f.read().strip())
        except OSError:
            continue
        if "pinctrl" in label or "bcm" in label:
            return base + bcm
    return bcm


SPEAKER_PIN = str(_sysfs_pin_number(SPEAKER_BCM))
SPEAKER_PATH = f"/sys/class/gpio/gpio{SPEAKER_PIN}"


# =============================================================================
# Shared state between threads
# =============================================================================

state_lock = threading.Lock()
last_bat_time = 0.0
last_bat_freq = 0.0
last_dist_cm = 0
stop_event = threading.Event()


# =============================================================================
# Speaker (adapted from speaker4.py)
# =============================================================================

def setup_speaker():
    if not os.path.exists(SPEAKER_PATH):
        try:
            with open("/sys/class/gpio/export", "w") as f:
                f.write(SPEAKER_PIN)
            time.sleep(0.1)
        except PermissionError:
            print("ERROR: cannot export GPIO. Try running with sudo, "
                  "or add your user to the 'gpio' group.", file=sys.stderr)
            return False
    with open(f"{SPEAKER_PATH}/direction", "w") as f:
        f.write("out")
    return True


def cleanup_speaker():
    if os.path.exists(SPEAKER_PATH):
        try:
            with open("/sys/class/gpio/unexport", "w") as f:
                f.write(SPEAKER_PIN)
        except Exception:
            pass


def trigger_beep(duration, frequency):
    """Toggle the speaker pin as a square wave. Same tone-generation as speaker4.py."""
    period = 1.0 / frequency
    half_period = period / 2.0
    cycles = int(duration * frequency)
    # Binary unbuffered mode: Python 3.13 forbids buffering=0 in text mode.
    with open(f"{SPEAKER_PATH}/value", "wb", buffering=0) as f:
        for _ in range(cycles):
            f.write(b"1")
            time.sleep(half_period)
            f.write(b"0")
            time.sleep(half_period)


# =============================================================================
# LiDAR worker (adapted from readsensor.py)
# =============================================================================

def lidar_worker():
    global last_dist_cm
    try:
        ser = serial.Serial(LIDAR_PORT, LIDAR_BAUD, timeout=1)
    except Exception as e:
        print(f"[lidar] ERROR opening {LIDAR_PORT}: {e}", file=sys.stderr)
        return

    print(f"[lidar] reading {LIDAR_PORT} @ {LIDAR_BAUD}")
    try:
        while not stop_event.is_set():
            b = ser.read(1)
            if not b or b != b"\x59":
                continue
            if ser.read(1) != b"\x59":
                continue
            frame = ser.read(7)
            if len(frame) < 7:
                continue
            dist = frame[0] + frame[1] * 256
            with state_lock:
                last_dist_cm = dist
    finally:
        ser.close()


# =============================================================================
# Bat FFT worker (adapted from 260703_detectorplswork.py)
# =============================================================================

def read_exact(ser, n_bytes):
    """Read exactly n_bytes from a serial stream, handling partial reads."""
    buf = bytearray()
    while len(buf) < n_bytes and not stop_event.is_set():
        chunk = ser.read(n_bytes - len(buf))
        if not chunk:
            continue
        buf.extend(chunk)
    return bytes(buf)


def bat_worker():
    global last_bat_time, last_bat_freq
    try:
        ser = serial.Serial(PICO_PORT, baudrate=PICO_BAUD, timeout=1)
    except Exception as e:
        print(f"[bat] ERROR opening {PICO_PORT}: {e}", file=sys.stderr)
        return

    print(f"[bat] reading {PICO_PORT} (PCM stream), "
          f"listening in {BAND_LO_HZ // 1000}-{BAND_HI_HZ // 1000} kHz")

    freqs = np.fft.rfftfreq(WINDOW_SIZE, d=1.0 / SAMPLE_RATE)
    band_mask = (freqs >= BAND_LO_HZ) & (freqs <= BAND_HI_HZ)
    band_freqs = freqs[band_mask]
    if not np.any(band_mask):
        print("[bat] ERROR: no FFT bins fall in the target band; "
              "increase WINDOW_SIZE.", file=sys.stderr)
        ser.close()
        return

    window_fn = np.hanning(WINDOW_SIZE)
    sample_buf = np.zeros(WINDOW_SIZE, dtype=np.float32)
    bytes_per_hop = HOP_SIZE * 2  # int16 = 2 bytes/sample

    try:
        # Prime the buffer with a full window
        raw = read_exact(ser, WINDOW_SIZE * 2)
        if stop_event.is_set():
            return
        sample_buf[:] = np.frombuffer(raw, dtype="<i2").astype(np.float32)

        while not stop_event.is_set():
            raw = read_exact(ser, bytes_per_hop)
            if stop_event.is_set():
                break
            new_samples = np.frombuffer(raw, dtype="<i2").astype(np.float32)

            sample_buf = np.roll(sample_buf, -HOP_SIZE)
            sample_buf[-HOP_SIZE:] = new_samples

            spectrum = np.fft.rfft(sample_buf * window_fn)
            magnitude = np.abs(spectrum)
            band_mag = magnitude[band_mask]
            peak_idx = int(np.argmax(band_mag))
            peak_mag = float(band_mag[peak_idx])
            peak_freq = float(band_freqs[peak_idx])

            if peak_mag > FFT_THRESHOLD:
                with state_lock:
                    last_bat_time = time.monotonic()
                    last_bat_freq = peak_freq
    finally:
        ser.close()


# =============================================================================
# Main coincidence + adaptive-beep loop
# =============================================================================

def compute_beep(dist_cm):
    """
    Given a current distance in cm, return (duration_s, frequency_hz, period_s)
    describing the next beep to play. Returns None if the object is out of range
    (i.e., no beep at all).

    Mirrors the "parking sensor" behavior from speaker4.py:
      - dist < SOLID_CM      → hold a near-solid loud tone (period ≈ 0)
      - SOLID_CM..RANGE_CM   → beeps that get faster + higher-pitched closer in
      - >= RANGE_CM          → silent
    """
    if dist_cm <= 0:
        return None
    if dist_cm < SOLID_CM:
        # Solid alarm: period 0 so the main loop re-fires immediately.
        return SOLID_DURATION_S, SOLID_FREQ, 0.0
    if dist_cm < RANGE_CM:
        f = dist_cm / RANGE_CM  # 0.0 at sensor, 1.0 at edge
        period = BEEP_PERIOD_NEAR + f * (BEEP_PERIOD_FAR - BEEP_PERIOD_NEAR)
        freq = int(BEEP_FREQ_NEAR + f * (BEEP_FREQ_FAR - BEEP_FREQ_NEAR))
        return BEEP_DURATION_S, freq, period
    return None


def main():
    if not setup_speaker():
        sys.exit(1)

    lidar_thread = threading.Thread(target=lidar_worker, daemon=True)
    bat_thread = threading.Thread(target=bat_worker, daemon=True)
    lidar_thread.start()
    bat_thread.start()

    print(f"[main] armed: bat call + object <{RANGE_CM}cm -> parking-sensor beeps; "
          f"<{SOLID_CM}cm -> solid alarm; bat gate = {COINCIDENCE_WINDOW_S:.1f}s")

    last_beep = 0.0
    try:
        while True:
            time.sleep(0.02)
            now = time.monotonic()

            with state_lock:
                bat_hot = (now - last_bat_time) < COINCIDENCE_WINDOW_S
                dist_snap = last_dist_cm
                freq_snap = last_bat_freq

            # Gate 1: no beeps at all unless a bat was recently heard.
            if not bat_hot:
                continue

            # Gate 2: distance decides duration/frequency/period (or "silent").
            beep = compute_beep(dist_snap)
            if beep is None:
                continue

            duration, frequency, period = beep

            # Gate 3: don't fire more often than the current period allows.
            if (now - last_beep) < period:
                continue

            print(f"[{time.strftime('%H:%M:%S')}] BEEP: "
                  f"bat ~{freq_snap / 1000:.1f} kHz + dist {dist_snap} cm "
                  f"-> {frequency} Hz for {duration * 1000:.0f} ms "
                  f"(next in {period * 1000:.0f} ms)")
            trigger_beep(duration=duration, frequency=frequency)
            last_beep = time.monotonic()
    except KeyboardInterrupt:
        print("\n[main] stopping.")
    finally:
        stop_event.set()
        time.sleep(0.2)
        cleanup_speaker()


if __name__ == "__main__":
    main()
