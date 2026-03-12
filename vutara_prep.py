import marimo

__generated_with = "0.18.4"
app = marimo.App(width="medium")


@app.cell
def _():
    import time
    import cv2
    import tiffile
    from pathlib import Path
    from returns.pipeline import is_successful

    #Find and import stage and camera drivers from various directories
    from prior.controller import PriorSDK, architecture

    try:
        from pipython import GCSDevice

        
    except ImportError:
        raise ImportError("PIPython not found. Please run 'uv pip install PIPython'")

    x = 6500     #x position in um
    y = 11250     #y position in um
    z = 300      #z position in um
    piezo_com = 5   #Which COM port is the prior piezo?
    stage_com = 3   #Which COM port is the prior stage?
    baud_rate = 9600

    def main():
        print("Initializing...")

        #Set up DLL path for stage
        arch_prefix = "x86" if architecture() == 32 else "x64"
        dll_path = Path(__file__).parent / "prior" / arch_prefix / "PriorScientificSDK.dll"

        # Initialize SDK Context
        # The SDK is designed to be used as a context manager (with statement).
        # This automatically handles session creation and cleanup (closing the session).
        sdk_xy = PriorSDK(dll_path=dll_path)
        pidevice = GCSDevice('E-709')

        with sdk_xy as xy_res, pidevice:
            if not is_successful(xy_res):
                print("failed to load SDK for xy control.")
                return

            ctrl_xy = xy_res.unwrap()

            xy_cont = ctrl_xy.connect(stage_com)
    
            if not is_successful(xy_cont):
                print(f"Failed to connect to XY stage on COM{stage_com}")
                return
            else: 
                print(f"Successfully connected to XY stage on COM{stage_com}")

            #Connect to the Z stage
            try:
                pidevice.ConnectRS232(piezo_com, baud_rate)
                print(f"Successfully connected to piezo controller on COM{piezo_com}")

                z_axis = pidevice.axes[0]

                if not pidevice.qSVO(z_axis)[z_axis]:
                    print("Enabling Z-axis servo...")
                    pidevice.SVO(z_axis, 1)
            except Exception as e:
                print(f"Failed to connect to PI Z stage on COM{piezo_com}.")
                print(f"Error details: {e}")
                return                    


            print("Both controllers connected!")    
            xstage = ctrl_xy.stage
            print(f"Moving Z Piezo to {z} um...")
            pidevice.MOV(z_axis, z)

            pidevice.qONT(z_axis)    #Wait until "on target"
            print("Move Z command sent")

            print(f"Moving XY Stage to X={x} um, Y={y} um...")
            xy_move = xstage.goto(x,y)
            if not is_successful(xy_move):
                print(f"XY Move Failed: {xy_move.failure()}")
            else:
                print("Move XY command sent.")

        print("Ready for tiling scan!")

    if __name__ == "__main__":
        main()


    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
