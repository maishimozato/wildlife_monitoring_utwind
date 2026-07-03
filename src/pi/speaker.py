import time
import gpiod
import serial

# Use the physical pin numbering or BCM numbering
# Pin 12 on the board corresponds to BCM GPIO 18
BEEP_PIN = 18 

chip = gpiod.Chip('gpiochip0')
line = chip.get_line(BEEP_PIN)

# Configure the pin as an output
config = gpiod.LineRequest(consumer='speaker_beep', type=gpiod.LineRequest.DIRECTION_OUTPUT)
line.request(config)

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
        line.set_value(1) # HIGH
        time.sleep(delay)
        line.set_value(0) # LOW
        time.sleep(delay)

try:
    print("LiDAR monitoring emulation starting... (Press Ctrl+C to stop)")
    ser = serial.Serial("/dev/serial0", 115200, timeout=1)
    while True:
        if ser.read() == b'\x59' and ser.read() == b'\x59':
            frame = ser.read(7)
            dist = frame[0] + frame[1]*256
            strength = frame[2] + frame[3]*256
            print(f"Distance: {dist} cm | Strength: {strength}")
            if dist < 100:  # Example threshold for bat detection
                print("Object detected! Beeping...")
                trigger_beep(duration=0.15, frequency=1200) # Short sharp warning beep
        # -------------------------------------------------------------
        # PLACE YOUR LIDAR DETECTION CODE HERE
        # e.g., if lidar.distance < 100:
        # -------------------------------------------------------------
        
        # Emulating a detection event every 3 seconds for testing:
        #time.sleep(3)

except KeyboardInterrupt:
    print("\nReleasing GPIO pin...")
    line.release()