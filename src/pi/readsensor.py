#print("should run \"sudo raspi-config\"" + " and then \"pip3 install pyserial\"")

import serial

ser = serial.Serial("/dev/serial0", 115200, timeout=1)

object_dectected = False
while True:
    if ser.read() == b'\x59' and ser.read() == b'\x59':
        frame = ser.read(7)
        dist = frame[0] + frame[1]*256
        strength = frame[2] + frame[3]*256
        print(f"Distance: {dist} cm | Strength: {strength}")
        if dist < 500:  # Example threshold for bat detection
            object_dectected = True


"""
bash:
stty -F /dev/serial0 115200 raw -echo
"""
"""

with open("/dev/serial0", "rb", buffering=0) as ser:
    while True:
        if ser.read(1) == b'\x59' and ser.read(1) == b'\x59':
            frame = ser.read(7)
            dist = frame[0] + frame[1] * 256
            strength = frame[2] + frame[3] * 256
            print(f"Distance: {dist} cm | Strength: {strength}")
"""