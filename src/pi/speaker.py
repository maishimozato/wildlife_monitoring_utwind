import time
import os
import serial

# Pin 12 on the board corresponds to BCM GPIO 18
PIN_NUM = "18"
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
    
    # Open the direct file value controller
    with open(f"{SYSFS_PATH}/value", "w", buffering=0) as f:
        for _ in range(cycles):
            f.write("1") # Pin HIGH
            time.sleep(delay)
            f.write("0") # Pin LOW
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