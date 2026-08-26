#!/usr/bin/python
# -*- coding: utf-8 -*-

from pipython import GCSDevice
from pipython.pitools import waitontarget
import time

class PIStageController:
    def __init__(self, dev_name='E-709'):
        """Initializes the PI GCS Device interface for the E-709 controller."""
        self.pidevice = GCSDevice(dev_name)
        self.axis = None

    def __enter__(self):
        return self

    def connect(self):
        """Opens the UI setup dialog for USB/Serial connection and initializes the axis."""
        try:
            # Opens the standard PI selection dialog (or connects if key matches saved profile)
            self.pidevice.InterfaceSetupDlg(key='E-709_USB')
            print(f"PI Stage Connected: {self.pidevice.qIDN().strip()}")
            
            # E-709 is a single-axis controller, grab its axis descriptor (typically '1' or 'A')
            self.axis = self.pidevice.axes[0]
            
            # Ensure the servo is ON (Closed-loop mode) for precision position tracking
            if self.pidevice.HasSVO():
                self.pidevice.SVO(self.axis, True)
                
            return True
        except Exception as e:
            print(f"CRITICAL: Failed to connect or initialize PI E-709: {e}")
            return False

    @property
    def position(self):
        """Queries and returns the current Z-axis position in micrometers."""
        positions = self.pidevice.qPOS(self.axis)
        return positions[self.axis]

    def move(self, target_step):
        """
        Moves the single-axis focus stage relatively.
        target_step: distance to move in micrometers (positive or negative)
        """
        try:
            current_pos = self.position
            destination = current_pos + target_step
            
            # Command an absolute move to the calculated offset destination
            self.pidevice.MOV(self.axis, destination)
            
            # Block until the closed-loop stage settles within target tolerance
            waitontarget(self.pidevice, axes=self.axis)
            return True
        except Exception as e:
            print(f"PI Stage relative move failed: {e}")
            return False

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Ensures safe disconnection when exiting context blocks."""
        if hasattr(self, 'pidevice'):
            print("Closing PI Stage connection...")
            self.pidevice.CloseConnection()