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
    from hamamatsu.hamamatsu.dcam import copy_frame, dcam, Stream

    width = 1000    #Scan width in um
    height = 1000   #scan height in um
    step = 500       #step size in um
    expos = 0.1     #exposure time in s
    stage_com = 3   #Which COM port is the prior stage?

    write_dir = Path("./scans/test")      #change the last folder to name the sample being scanned
    write_dir.mkdir(exist_ok=True)
    name_prefix = "custom_"          #change the "custom" to which microscope took the data

    def main():
        print("Starting Scan:")

        #Set up DLL path for stage
        arch_prefix = "x86" if architecture() == 32 else "x64"
        dll_path = Path(__file__).parent / "prior" / arch_prefix / "PriorScientificSDK.dll"

        # Initialize SDK Context
        # The SDK is designed to be used as a context manager (with statement).
        # This automatically handles session creation and cleanup (closing the session).
        with PriorSDK(dll_path=dll_path) as sdk_result:

            # The SDK returns a Result object (Success or Failure)
            if not is_successful(sdk_result):
                print(f"CRITICAL: Failed to initialize SDK session: {sdk_result.failure()}")
                return

            # Unwrap the controller instance from the Success result
            controller = sdk_result.unwrap()

            print(f"Connecting to controller on COM{stage_com}...")
            connect_res = controller.connect(stage_com)

            if not is_successful(connect_res):
                print(f"Connection failed: {connect_res.failure()}")

            stage = controller.stage        
            print("Session opened successfully.")
            with dcam:
                camera = dcam[0]
                with camera:
                    camera["exposure_time"] = expos

                    xsteps = int(width / step)
                    ysteps = int(height / step)

                    nimages = xsteps * ysteps
                    imcount = 0

                    print(f"Starting Scan: {xsteps}x{ysteps} for a total of {nimages} pics")
                    print(f"with each pic being {step}um apart")

                    for y in range(ysteps):
                        for x in range(xsteps):
                            #First, take a picture
                            with Stream(camera, 1) as stream:
                                camera.start()
                                for frame_buffer in stream:
                                    frame = copy_frame(frame_buffer)

                                    frame = frame.astype('uint16')
                                    filename = f"{name_prefix}{imcount:04d}.tiff"
                                    save_path = write_dir / filename
                                    tiffile.imwrite(save_path, frame)

                                    imcount += 1

                            #Now we'll move the stage in x
                            if x < xsteps - 1:
                                slide = stage.move(step, 0)
                                cpos = stage.position
                                if not is_successful(slide):
                                    print(f"Stage move failed at {cpos}")
                                    return

                            #If we need to move the stage in y, we're going to do a carriage return and then resume
                            if x == xsteps - 1:
                                xreset = -1 * (xsteps - 1) * step
                                print(f"End of row {y}/{ysteps}, Returning X and stepping Y.")
                                slide = stage.move(xreset, step)
                                cpos = stage.position
                                if not is_successful(slide):
                                    print(f"Stage move failed at {cpos}")
                                    return
        print("Scan completed successfully!")

    if __name__ == "__main__":
        main()
    return


@app.cell
def _():
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
