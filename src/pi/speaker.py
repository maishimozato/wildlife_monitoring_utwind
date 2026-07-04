import time
import os
import glob
import serial

# Pin 12 on the board corresponds to BCM GPIO 18
PIN_BCM = 18


def _sysfs_pin_number(bcm):
    """
    On kernel 6.6+ the sysfs GPIO chip base moved off zero (Pi 4 uses base 512),
    so the sysfs pin number = base + BCM number. Older kernels had base=0 and
    the BCM number was used directly. This function figures it out at runtime
    by reading /sys/class/gpio/gpiochip*/label and /base.
    """
    for chip in glob.glob("/sys/class/gpio/gpiochip*"):
        try:
            with open(f"{chip}/label") as f:
                label = f.read().strip().lower()
            with open(f"{chip}/base") as f:
                base = int(f.read().strip())
        except OSError:
            continue
        # main SoC GPIO chip is labeled like 'pinctrl-bcm2711' (Pi 4) / 'pinctrl-bcm2835'
        if "pinctrl" in label or "bcm" in label:
            return base + bcm
    return bcm  # fallback: old kernels where base was 0


PIN_NUM = str(_sysfs_pin_number(PIN_BCM))
SYSFS_PATH = f"/sys/class/gpio/gpio{PIN_NUM}"

def setup_gpio():
    """Initializes the GPIO pin using native Linux filesystem commands."""
    # If the pin is not already exported by the OS, export it
    if not os.path.exists(SYSFS_PATH):
        try:
            with open("/sys/class/gpio/export", "w") as f:
                f.write(PIN_NUM)
            time.sleep(0.1) # Brief pause for Linux to create the file directory
        except Exception as e:
            print(f"Error exporting pin: {e}. Try running script with 'sudo'.")
            return False

    # Configure the pin direction to output
    with open(f"{SYSFS_PATH}/direction", "w") as f:
        f.write("out")
    return True

def trigger_beep(duration=0.15, frequency=1200):
    """
    Generates a beep sound by opening the Linux file node 
    and flipping the bit directly in a tight loop.
    """
    period = 1.0 / frequency
    delay = period / 2.0
    cycles = int(duration * frequency)
    
    # Open in BINARY unbuffered mode. Python 3.13 forbids buffering=0 in text mode.
    with open(f"{SYSFS_PATH}/value", "wb", buffering=0) as f:
        for _ in range(cycles):
            f.write(b"1")  # Pin HIGH
            time.sleep(delay)
            f.write(b"0")  # Pin LOW
            time.sleep(delay)

def cleanup_gpio():
    """Cleans up the pin layout upon exit."""
    if os.path.exists(SYSFS_PATH):
        try:
            with open("/sys/class/gpio/unexport", "w") as f:
                f.write(PIN_NUM)
        except:
            pass

try:
    print("Initializing offline native GPIO...")
    if not setup_gpio():
        exit(1)
        
    print("LiDAR monitoring active... Listening on /dev/serial0")
    ser = serial.Serial("/dev/serial0", 115200, timeout=1)
    
    while True:
        if ser.in_waiting >= 9:
            if ser.read() == b'\x59' and ser.read() == b'\x59':
                frame = ser.read(7)
                if len(frame) == 7:
                    dist = frame[0] + frame[1] * 256
                    strength = frame[2] + frame[3] * 256
                    print(f"Distance: {dist} cm | Strength: {strength}")
                    
                    if 0 < dist < 100:
                        print("Object detected! Beeping...")
                        trigger_beep(duration=0.15, frequency=1200)
        else:
            time.sleep(0.01)

except KeyboardInterrupt:
    print("\nShutting down and cleaning up GPIO...")
    cleanup_gpio()
    ser.close()