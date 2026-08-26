#!/usr/bin/python
# -*- coding: utf-8 -*-

import time
from pi.controller import PIStageController
from pipython.pitools import waitontarget

def test_piezo():
    print("==================================================")
    print("Starting PI E-709 Piezo Functionality Test")
    print("==================================================")

    # 1. Connect to the piezo
    with PIStageController(dev_name='E-709') as controller:
        if not controller.connect():
            print("[-] Test aborted: Could not connect to the stage.")
            return
        
        # Extract the internal device reference and axis for limit querying
        dev = controller.pidevice
        axis = controller.axis
        
        # Read physical travel limits from the controller
        min_limit = dev.qTMN(axis)[axis]
        max_limit = dev.qTMX(axis)[axis]
        
        print(f"[+] Connection verified!")
        print(f"[+] Current Position: {controller.position:.3f} um")
        print(f"[+] Controller Travel Limits: Min = {min_limit:.3f} um | Max = {max_limit:.3f} um")
        print("--------------------------------------------------")
        
        time.sleep(1.0)

        # 2. Move to the minimum value
        print(f"[>] Moving to MINIMUM limit: {min_limit:.3f} um...")
        dev.MOV(axis, min_limit)
        waitontarget(dev, axes=axis)
        print(f"[✓] Arrived at: {controller.position:.3f} um")
        
        time.sleep(1.5) # Pause briefly to observe

        # Move to the maximum value
        print(f"[>] Moving to MAXIMUM limit: {max_limit:.3f} um...")
        dev.MOV(axis, max_limit)
        waitontarget(dev, axes=axis)
        print(f"[✓] Arrived at: {controller.position:.3f} um")
        
        time.sleep(1.5)

# 3. Reset to 0
        print("[>] Resetting position back to 0.000 um...")
        dev.MOV(axis, 0.0)
        waitontarget(dev, axes=axis)
        
        # Add a tiny 100-200ms pause to let the piezo fully settle into its closed-loop valley
        time.sleep(0.2) 
        
        print(f"[✓] Arrived at: {controller.position:.3f} um")
        print("--------------------------------------------------")
        
        # 4. Connection closes automatically here via __exit__
        print("[+] Test routine finished successfully inside context block.")

    print("[+] Connection safely closed. Stage is offline.")
    print("==================================================")

if __name__ == '__main__':
    test_piezo()