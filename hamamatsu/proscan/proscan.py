import serial
import threading
import contextlib
import typing

# for accessing parent class in directory above
# source: https://stackoverflow.com/questions/1054271/how-to-import-a-python-class-that-is-in-a-directory-above 
import sys
import os.path
sys.path.append(
    os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))
)

from proscan.base_stage import BaseStage

# based on _ProScanIII Connection for Python-Microscope
# link: https://github.com/python-microscope/microscope/blob/master/microscope/controllers/prior.py
class _PriorConnection:
    """
    Wraps serial connection with a reentrant lock
    This class wraps pySerial's serial.Serial, for the stage's connection via Serial Port
    
    """

    def __init__(self, port: str) -> None:
        self._serial = serial.Serial(
            port=port,
            baudrate=9600, # based on eeDAP source code
            timeout=3, # also based on eeDAP source code
            bytesize=serial.EIGHTBITS, # using an 8 bit word
            stopbits=serial.STOPBITS_ONE, # one stop bit
            parity=serial.PARITY_NONE, # no parity or handshake
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )

        self._lock = threading.RLock()

        with self._lock:
            # Get a response from the ProScan controller
            # asking for ProScan description
            self.write(b"?")
            response = self._serial.read_until(b"\r")

            if response != b"PROSCAN INFORMATION\r":
                self.read_until_timeout()
                raise RuntimeError(
                    "'%s' does not respond like a Prior device" % response.decode()
                )

            # read until the end of the description
            line = self._serial.read_until(b"\rEND\r")

            if not line.endswith(b"\rEND\r"):
                raise RuntimeError("Failed to clear description")

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    @contextlib.contextmanager
    def temp_change_timeout(self, new_timeout: float):
        prev = self._serial.timeout
        try:
            self._serial.timeout = new_timeout
            yield
        finally:
            self._serial.timeout = prev

    def write(self, data: bytes) -> int:
        with self.lock:
            return self._serial.write(data + b"\r")

    def readline(self) -> bytes:
        with self.lock:
            return self._serial.read_until(b"\r")

    def validate_response(self, command: bytes, expected_responses: list) -> None:
        with self.lock:
            with self.temp_change_timeout(10 * self._serial.timeout):
                self.write(command)
                response = self.readline()
                print("Response: " + response.decode("ASCII"))
                for i in range(len(expected_responses)):
                    candidate = expected_responses[i]

                    if response != candidate:

                        # go to next candidate in the list
                        if i < (len(expected_responses) - 1):
                            continue

                        # these errors are based on ProScanIII manual and eeDAP source code
                        # ProScanIII manual: https://www.prior.com/wp-content/uploads/2017/06/ProScanIII-v1.12.pdf?msclkid=2d7d7419d09711ecb06bff0c15fa4cf2
                        # Software Commands under Section 4 of the manual
                        if response == b'E,1\r':
                            print("No Prior Stage connected")
                        if response == b'E,2\r':
                            print("Prior Stage not idle")
                        if response == b'E,3\r':
                            print("No Prior driver")
                        if response == b'E,4\r':
                            print("String parsing error")
                        if response == b'E,5\r':
                            print("Command for Prior Stage not found")
                        if response == b'E,8\r':
                            print("Value out of range")

                        self.read_until_timeout()
                        raise RuntimeError(
                            "Command failed: '%s'\n \
                            Expected Response: '%s'\n \
                            Got: '%s'\n" %(command.decode("ASCII"), candidate.decode("ASCII"), response.decode("ASCII"))
                        )
                    else:
                        break

                # self.read_until_timeout()


    def read_until_timeout(self) -> None:
        """ cleans buffer if in unknown state """
        with self.lock:
            self._serial.flushInput()
            while self._serial.readline():
                continue

    def close(self) -> None:
        return self._serial.close()

# custom classes for errors in Prior Stage
class Error(Exception):
    """ base Exception class """
    pass

class MissingCoordinate(Error):
    """ if either the x or y coordinate is not supplied for
    move command, print custom error message 
    called in PriorStage method move_to()"""
    pass

# also based on _ProScanIII class from Python-Microscope
# link at the top of this code
# also inspired by the Stage class from Python-Microscope
# link: https://github.com/python-microscope/microscope/blob/master/microscope/abc.py
class PriorStage(BaseStage):
    def __init__(self, port=str):
        super().__init__(port)
        self.connection = _PriorConnection(port)

    def move_to(self, delta: typing.Mapping[str, float]) -> None:
        try:
            # extract floats for x and y coordinates
            x = delta["x"]
            y = delta["y"]

            # if one of the coordinates is missing, throw error
            if x is None or y is None:
                raise MissingCoordinate

            # convert the coordinates to bytes
            x_input = bytes(str(x), 'ascii')
            y_input = bytes(str(y), 'ascii')

            # define the move command
            # e.g. to move to coordinates (100, 200)
            # input for Prior = b'G 100,200'
            command = b'G '+ x_input + b',' + y_input

            # print goal position to terminal
            print("Moving to (" + str(x) + ", " + str(y) + ")")

            # send command through serial port and validate response
            self.connection.validate_response(command, [b'R\r'])

        except MissingCoordinate:
            print("must supply both x and y coordinate")

    def close(self) -> None:
        """ Close the serial port connection """
        try:
            self.connection.close()
            print("Successfully closed")
        except:
            print("Unable to close serial port")

