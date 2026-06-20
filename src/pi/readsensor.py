print("should run \"sudo raspi-config\"" + " and then \"pip3 install pyserial\"")

import serial

ser = serial.Serial("/dev/serial0", 115200, timeout=1)

while True:
    if ser.read() == b'\x59' and ser.read() == b'\x59':
        frame = ser.read(7)
        dist = frame[0] + frame[1]*256
        strength = frame[2] + frame[3]*256
        print(f"Distance: {dist} cm | Strength: {strength}")