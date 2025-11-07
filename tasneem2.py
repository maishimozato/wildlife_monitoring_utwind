#hi
import os
import random 
print("Hello World!")

x = random.randint(1,10)
guess = input("Guess a number from 1-10")

while guess != x:
    guess = input("wrong! guess again :()")
    break

print("yayyy")