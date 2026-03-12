import marimo

__generated_with = "0.18.4"
app = marimo.App(width="medium")


@app.cell
def _():
    import serial.tools.list_ports

    def list_ports():
        ports = serial.tools.list_ports.comports()
        if not ports:
            print("No COM ports found! Check USB connection and power.")
            return
    
        print("Available Ports:")
        for port, desc, hwid in ports:
            print(f" -> {port}: {desc}")

    if __name__ == "__main__":
        list_ports()
    return


if __name__ == "__main__":
    app.run()
