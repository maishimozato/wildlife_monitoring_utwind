import time
import RPi.GPIO as GPIO

# Use the physical pin numbering or BCM numbering
# Pin 12 on the board corresponds to BCM GPIO 18
BEEP_PIN = 18 

GPIO.setmode(GPIO.BCM)
GPIO.setup(BEEP_PIN, GPIO.OUT)

def trigger_beep(duration=0.2, frequency=1000):
    """
    Generates a beep sound by toggling the GPIO pin.
    duration: how long the beep lasts (seconds)
    frequency: pitch of the beep (Hz)
    """
    period = 1.0 / frequency
    delay = period / 2.0
    cycles = int(duration * frequency)
    
    for _ in range(cycles):
        GPIO.output(BEEP_PIN, GPIO.HIGH)
        time.sleep(delay)
        GPIO.output(BEEP_PIN, GPIO.LOW)
        time.sleep(delay)

try:
    print("LiDAR monitoring emulation starting... (Press Ctrl+C to stop)")
    while True:
        # -------------------------------------------------------------
        # PLACE YOUR LIDAR DETECTION CODE HERE
        # e.g., if lidar.distance < 100:
        # -------------------------------------------------------------
        
        # Emulating a detection event every 3 seconds for testing:
        print("Object detected! Beeping...")
        trigger_beep(duration=0.15, frequency=1200) # Short sharp warning beep
        
        time.sleep(3)

except KeyboardInterrupt:
    print("\nCleaning up GPIO pins...")
    GPIO.cleanup()