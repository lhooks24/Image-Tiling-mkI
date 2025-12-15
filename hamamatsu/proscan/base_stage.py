from abc import ABCMeta, abstractmethod
import typing
import threading

# based on Openflexure base stage class and Python-Microscope ProScanIII classe
# link for Python-Microscope ProScanIII class: https://github.com/python-microscope/microscope/blob/master/microscope/controllers/prior.py
# link for Openflexure base stage class: https://gitlab.com/openflexure/openflexure-microscope-server/-/blob/master/openflexure_microscope/stage/base.py 
class BaseStage(metaclass=ABCMeta):
    """
    Attributes:

        lock (:py:class:`labthings.StrictLock`): Strict lock controlling thread
            access to stage hardware

            TODO change this
    """

    def __init__(self, port: str):
        self.port = port
        self.lock = threading.RLock()

    @abstractmethod
    def move_to(self, delta: typing.Mapping[str, float]) -> None:
        """ move stage to a position (x, y) """
        raise NotImplementedError()

    @abstractmethod
    def close(self):
        """Cleanly close communication with the stage"""
        raise NotImplementedError()