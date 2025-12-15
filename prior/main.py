from pathlib import Path

from returns.pipeline import is_successful

# Import the wrapper classes from controller.py
# We use a try-except block to handle running this script directly or as a module
try:
    from controller import PriorSDK, architecture
except ImportError:
    from prior.controller import PriorSDK, architecture


def main():
    # 1. Setup DLL Path
    # Calculate path relative to this script to ensure the DLL is found
    arch_prefix = "x86" if architecture() == 32 else "x64"
    dll_path = Path(__file__).parent / arch_prefix / "PriorScientificSDK.dll"

    print(f"Initializing SDK with DLL at: {dll_path}")

    # 2. Initialize SDK Context
    # The SDK is designed to be used as a context manager (with statement).
    # This automatically handles session creation and cleanup (closing the session).
    with PriorSDK(dll_path=dll_path) as sdk_result:
        
        # The SDK returns a Result object (Success or Failure)
        if not is_successful(sdk_result):
            print(f"CRITICAL: Failed to initialize SDK session: {sdk_result.failure()}")
            return

        # Unwrap the controller instance from the Success result
        controller = sdk_result.unwrap()
        print("Session opened successfully.")

        # 3. Connect to the Controller
        # Update this port number to match your hardware (e.g., 3 for COM3)
        COM_PORT = 3 
        print(f"Connecting to controller on COM{COM_PORT}...")
        
        connect_res = controller.connect(COM_PORT)
        
        if not is_successful(connect_res):
            print(f"Connection failed: {connect_res.failure()}")
            # Attempt to read the specific error from the controller
            print(f"Controller Last Error: {controller.last_error}")
            return

        print("Connected!")

        # 4. Read Controller Info
        # Properties like model and serial_number return values directly
        print(f"Model: {controller.model}")
        print(f"Serial Number: {controller.serial_number}")
        
        # 5. Stage Operations
        stage = controller.stage

        # Get current position (returns a tuple of ints or None)
        start_pos = stage.position
        print(f"Start Position (microns): {start_pos}")

        # Check if stage is busy
        print(f"Stage Status: {stage.busy}")

        # Move Relative
        # Moves X by 100 microns and Y by 100 microns
        move_x, move_y = 100, 100
        print(f"Moving relative ({move_x}, {move_y})...")
        
        move_res = stage.move(move_x, move_y)
        
        if is_successful(move_res):
            print("Move command accepted.")
        else:
            print(f"Move command failed: {move_res.failure()}")

        # Check new position
        end_pos = stage.position
        print(f"End Position (microns): {end_pos}")
        
        # Example: Setting max speed (if supported by controller)
        # stage.speed = 100
        # print(f"Stage Speed set to: {stage.speed}")

    # Context manager exits here, automatically closing the SDK session.
    print("Session closed.")


if __name__ == "__main__":
    main()
