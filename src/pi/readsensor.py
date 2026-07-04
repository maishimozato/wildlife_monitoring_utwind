"""
Read a TFmini-style LiDAR over UART on the Raspberry Pi.

Prereqs on the Pi (one-time):
  1) sudo raspi-config
       Interface Options -> Serial Port
       login shell over serial? NO
       serial hardware enabled? YES
     then: sudo reboot
  2) sudo usermod -aG dialout $USER    (log out / back in)
  3) In your venv:  pip install pyserial

Then:  python3 readsensor.py
"""

import sys
import time

PORT = "/dev/serial0"
BAUD = 115200
BEEP_THRESHOLD_CM = 100
# Warn if this many seconds go by without a single valid frame.
NO_DATA_WARN_S = 3.0


try:
    import serial
except ImportError:
    print("ERROR: pyserial is not installed in this environment.", file=sys.stderr)
    print("Fix:   pip install pyserial   (with your venv activated)", file=sys.stderr)
    sys.exit(1)


def open_port():
    try:
        return serial.Serial(PORT, BAUD, timeout=1)
    except FileNotFoundError:
        print(f"ERROR: {PORT} does not exist.", file=sys.stderr)
        print("Fix:   sudo raspi-config -> Interface Options -> Serial Port", file=sys.stderr)
        print("         login shell over serial? NO", file=sys.stderr)
        print("         serial hardware enabled? YES", file=sys.stderr)
        print("       sudo reboot", file=sys.stderr)
        sys.exit(1)
    except PermissionError:
        print(f"ERROR: no permission to open {PORT}.", file=sys.stderr)
        print("Fix:   sudo usermod -aG dialout $USER   (then log out and back in)", file=sys.stderr)
        sys.exit(1)
    except serial.SerialException as e:
        print(f"ERROR opening {PORT}: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    ser = open_port()
    print(f"Reading from {PORT} @ {BAUD} baud. Ctrl+C to stop.")

    last_frame_time = time.monotonic()
    warned_no_data = False

    try:
        while True:
            b = ser.read(1)
            if not b:
                # timeout hit with no byte — check if we've been silent too long
                if not warned_no_data and (time.monotonic() - last_frame_time) > NO_DATA_WARN_S:
                    print(
                        f"WARNING: no bytes in {NO_DATA_WARN_S:.0f}s. "
                        "Check sensor 5V power and that sensor TX -> Pi RX (pin 10).",
                        file=sys.stderr,
                    )
                    warned_no_data = True
                continue

            # TFmini frame starts with 0x59 0x59, then 7 more bytes
            if b == b"\x59" and ser.read(1) == b"\x59":
                frame = ser.read(7)
                if len(frame) < 7:
                    continue
                dist = frame[0] + frame[1] * 256
                strength = frame[2] + frame[3] * 256
                print(f"Distance: {dist} cm | Strength: {strength}")
                if dist < BEEP_THRESHOLD_CM:
                    print("Object detected! Beeping...")

                last_frame_time = time.monotonic()
                warned_no_data = False
    except KeyboardInterrupt:
        print("\nstopping.")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
