import os
print("CWD:", os.getcwd())
print("Root /:", os.listdir("/"))
try:
    print("/flash:", os.listdir("/flash"))
except Exception as e:
    print("/flash err:", e)