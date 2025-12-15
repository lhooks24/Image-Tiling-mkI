# Prior Scientific Python SDK Wrapper

**⚠️ STATUS: TESTING PHASE ⚠️**

This library is currently in active development and is considered experimental. The API may change, and not all features of the Prior Scientific SDK are fully wrapped or tested yet. Use with caution.

## Overview

This project provides a modern, Pythonic wrapper around the Prior Scientific C++ SDK/DLLs. It simplifies interaction with Prior controllers (e.g., ProScan III) by managing the ctypes interfacing, session handling, and error checking, utilizing functional programming patterns (via the `returns` library) for robust operation.

## Prerequisites

* **Python**: 3.8 or newer (required for type hinting features).
* **Drivers**: Ensure the Prior Scientific SDK drivers are installed or the DLLs are present in the `x64/` or `x86/` directories included in this repo.
* **Hardware**: A Prior Scientific controller connected via USB/COM port.

## Installation

1.  **Clone/Download** this repository.
2.  **Install Dependencies**: This project relies on `returns` for result handling and `typing-extensions`.
    ```bash
    pip install returns typing-extensions
    ```

## Getting Started

A sample script is provided in `main.py` to demonstrate how to connect and move a stage.

1.  **Check your COM port**: Open `main.py` and ensure `COM_PORT` matches your device's port (e.g., `3` for `COM3`).
2.  **Run the script**:
    ```bash
    python main.py
    ```

### Basic Usage Example

```python
from pathlib import Path
from controller import PriorSDK, is_successful

# Initialize SDK (automatically handles DLL loading and Session open/close)
dll_path = Path(".") / "x64" / "PriorScientificSDK.dll"

with PriorSDK(dll_path=dll_path) as sdk_result:
    if is_successful(sdk_result):
        controller = sdk_result.unwrap()
        
        # Connect to COM3
        controller.connect(3)
        
        # Move Stage
        controller.stage.move(100, 100)
        
        print(f"Current Position: {controller.stage.position}")
```

## Validation & Troubleshooting

Since this wrapper is in the **Testing Phase**, you should verify hardware functionality using the original examples provided by Prior if you encounter issues.

**If `main.py` fails or behaves unexpectedly:**

1.  Navigate to the vendor examples: `prior/examples/python/`.
2.  Run the reference script:
    ```bash
    python prior/examples/python/prior_interface.py
    ```
3.  **Compare Results**:
      * If `prior_interface.py` works but `main.py` does not, there is likely a bug in this wrapper code.
      * If `prior_interface.py` also fails, check your hardware connections, power, and drivers.

## Project Structure

  * `controller.py`: Core wrapper logic containing `PriorController` and `PriorSDK` classes.
  * `main.py`: Main entry point for testing the wrapper.
  * `x64/` & `x86/`: Contains the `PriorScientificSDK.dll` binaries.
  * `examples/`: Original example scripts provided by Prior Scientific for reference.


