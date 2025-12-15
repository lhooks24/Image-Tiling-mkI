import serial.tools.list_ports as ports

com_ports = list(ports.comports())
for i in com_ports:
    print(i.device + " " + i.description)