from __future__ import annotations  # Must be the first line

from ctypes import WinDLL, c_int32, c_uint32, create_string_buffer
from pathlib import Path
from typing import Any, Generic, Optional, Tuple, TypeVar

from returns.pipeline import flow, is_successful
from returns.result import Failure, Result, Success
from typing_extensions import Self, deprecated


def architecture():
    import struct
    return struct.calcsize("P") * 8

# Default DLL path

_A_PREFIX = "x86" if architecture == 32 else "x64"
_DEFAULT_DLL_PATH = Path(".") / _A_PREFIX / "PriorScientificSDK.dll" 

T = TypeVar('T')
class PriorController:
    def __init__(self, sdk: PriorSDK) -> None:
        self._sdk = sdk

    def _cmd(self, cmd: str, *params: Any):
        return self._sdk._cmd(f"controller.{cmd}", *params)

    def _get(self, property: str, default: T = None) -> str | T:
        return self._cmd(f"{property}.get").value_or(default)

    def _set(self, property: str, value: Any) -> None:
        self._cmd(f"{property}.set", value)

    def connect(self, port: int):
        """
        Connect to the Prior Controller at the given port number.
        IE if port is 4, the controller would connect on port COM4.
        """
        return self._cmd("connect", port)
    
    @deprecated("This method is poorly documented and exists in this class purely for completeness. Be careful when using it.")
    def connect_nd(self, port: int):
        """
        Connect to the Prior controller at the given port number.
        IE if port is 4, the controller would connect on port COM4.
        It is unclear how this connection differs from connect.
        Unless you have a good reason, prefer connect.
        """
        return self._cmd("connect_nd", port)

    @property
    def last_error(self):
        """
        Holds the last error the controller reported.
        """
        return self._get("lasterror")

    @property
    def serial_number(self):
        """
        Holds the controller's serial number.
        """
        return self._get("serialnumber")

    @property
    def user_flag(self):
        """
        Holds the user flag value. A generic integer flag value controlled by the user.
        A common use is to have it as a warm start flag, whereby after connection you can determine
        whether the controller has been powered off since its last disconnect.
        """
        res = self._get("flag", "FFFFFFFF")
        return c_int32(int(res, base=16)).value

    @user_flag.setter
    def user_flag(self, value: int):
       u32 = c_uint32(value).value
       hexstr = f"{u32:X}"
       self._set("flag", hexstr)

    @property
    def model(self):
        return self._get("model")

    @property
    def interlock(self):
        return int(self._get("ilock", "0"))

    @property
    def stage(self):
        return Stage(self)

    def stop(self):
        """
        Stop all axes moving in a controlled fashion, maintaining positional accuracy.
        """
        return self._cmd("stop.smoothly")

    def force_stop(self):
        """
        Stop all axes moving immediately. Positional accuracy is not maintained.
        Reinitialization of individual axes is recommended.
        """
        return self._cmd("stop.abruptly")

class Stage:
    def __init__(self, controller: PriorController) -> None:
        self._controller = controller

    def _cmd(self, cmd: str, *params: Any):
        return self._controller._cmd(f"stage.{cmd}", *params)

    def _get(self, property: str, default: T = None) -> str | T:
        return self._cmd(f"{property}.get").value_or(default)

    def _set(self, property: str, value: Any) -> None:
        if isinstance(value, list) or isinstance(value, tuple):
            self._cmd(f"{property}.set", *value)
            return

        self._cmd(f"{property}.set", value)

    @property
    def busy(self):
        "Holds the busy status of the stage"
        busy_signal = int(self._get("busy", "0"))
        match busy_signal:
            case 0:
                return "IDLE"
            case 1:
                return "X_MOVING"
            case 2:
                return "Y_MOVING"
            case 3:
                return "XY_MOVING"
            case _:
                return "UNKNOWN"

    @property
    def position(self):
        """
        Holds the current stage XY position in the units set during configuration.
        Default resolution is microns.
        """
        res = self._get("position")
        if res is not None:
            return tuple(map(int, res.split(",")))

        return res

    @position.setter
    def position(self, value: Tuple[int, int]):
        """"
        Overwrite the position of the stage.
        Does not move the stage.
        Useful for stage homing.
        """
        self._set("position", value)

    @property
    def name(self):
        return self._get("name", None)

    @property
    def steps_per_micron(self):
        return int(self._get("steps-per-micron", 0))

    @property
    def limits(self):
        lim = int(self._get("limits", 0))
        xp = (lim & 0b0001)
        xn = (lim & 0b0010) >> 1
        yp = (lim & 0b0100) >> 2
        yn = (lim & 0b1000) >> 3

        return {"xp": xp, "xn": xn, "yp": yp, "yn": yn }

    @property
    def speed(self):
        """holds the max speed in microns/s"""
        return int(self._get("speed", 0))

    @speed.setter
    def speed(self, value: int):
        """Set the max speed in microns/s"""
        self._set("speed", value)

    @property
    def acceleration(self):
        """Holds the acceleration value in microns per second."""
        return int(self._get("acc", 0))

    @acceleration.setter
    def acceleration(self, value: int):
        """Set the acceleration value in microns per second."""
        self._set("acc", value)

    def set_lower_ylimit(self):
        """Set the current y position as the lower y limit"""
        return self._set("swlimits.low", "Y")

    def set_lower_xlimit(self):
        """Set teh current x position as the lower x limit"""
        return self._set("swlimits.low", "X")

    def set_upper_ylimit(self):
        """Set the current y position as the upper y limit"""
        return self._set("swlimits.high", "Y")

    def set_upper_xlimit(self):
        """Set teh current x position as the upper x limit"""
        return self._set("swlimits.high", "X")

    def clear_limits(self):
        """Clear the axis limits. Returns result for X and Y in that order."""
        return (
                self._cmd("swlimits.clear", "X"),
                self._cmd("swlimits.clear", "Y")
            )

    def goto(self, x: int, y: int):
        """Move to the absolute position in micons"""
        return self._cmd("goto-position", x, y)

    def move(self, x: int, y: int):
        """Move x,y microns relative to the current position"""
        return self._cmd("move-relative", x, y)


class PriorSDK:
    """
    Python SDK Wrapper for Prior Scientific Instruments.
    Based on DLL API Description & Command Set[cite: 2].
    """

    def __init__(self, dll_path: Path = _DEFAULT_DLL_PATH) -> None:
        self._session: int = -1
        self._init_result: Result[None, str] | None = None
        self._dirty_state: bool = False
        # Shared buffer for responses [cite: 345]
        self._rx = create_string_buffer(5000) 

        if dll_path.exists():
            try:
                self.SDKPrior = WinDLL(str(dll_path))
            except Exception as err:
                self._init_result = Failure(f"Dll could not be loaded. {err}")
                return
        else:
            self._init_result = Failure(f"Dll could not be found at {dll_path}.")
            return

        # Initialize the DLL [cite: 327]
        if ret := self.SDKPrior.PriorScientificSDK_Initialise():
            self._init_result = Failure(f"API Error: {ret}. Could not initialize API")
        else:
            self._init_result = Success(None)

    def __enter__(self) -> Result[PriorController, str]:
        if isinstance(self._init_result, Failure):
            return self._init_result

        # Open Session [cite: 334]
        sessionID = self.SDKPrior.PriorScientificSDK_OpenNewSession()
        if sessionID < 0:
            return Failure(f"Failed to initialize session. Error Code: {sessionID}.")
        
        self._session = sessionID
        return Success(PriorController(self))

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        # Close Session [cite: 337]
        if self._session >= 0:
            self.SDKPrior.PriorScientificSDK_CloseSession(self._session)
            self._session = -1

    def _cmd(self, tx: str, *params: Any) -> Result[str, int]:
        """
        Sends a command to the Prior controller.
        Ref: [cite: 342]
        """
        if self._session < 0:
            return Failure(-10004) # PRIOR_NOTCONNECTED

        # Format command string [cite: 353]
        param_str = " ".join(map(str, params))
        msg = f"{tx} {param_str}".strip()
        
        self._rx.value = b"" 

        ret = self.SDKPrior.PriorScientificSDK_cmd(
            self._session,
            create_string_buffer(msg.encode("utf-8")),
            self._rx
        )

        if ret != 0:
            return Failure(ret)
        
        # Decode response [cite: 345]
        return Success(self._rx.value.decode("utf-8"))

