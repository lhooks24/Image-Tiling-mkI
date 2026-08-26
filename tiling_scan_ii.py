import marimo

__generated_with = "0.18.4"
app = marimo.App(width="medium")


@app.cell
def _():
    import time
    import cv2
    import tiffile
    import logging
    import numpy as np
    from pathlib import Path
    from returns.pipeline import is_successful

    # Find and import stage and camera drivers
    from prior.controller import PriorSDK, architecture
    from hamamatsu.hamamatsu.dcam import copy_frame, dcam, Stream, EProp
    from hamamatsu.hamamatsu.dcam import EImagePixelType

    # --- CONFIGURATION ---
    width = 1000    # Scan width in um
    height = 1000   # scan height in um
    step = 250      # step size in um
    stage_com = 3   # Which COM port is the prior stage?

    # EXPOSURE SETTINGS
    exposure_time = 0.020  # Single exposure time in seconds
    pixel_gain = 0

    write_dir = Path("C:/Users/ladmin/OneDrive - University of Utah/grad school/research/Super-Res/Data/06_19_26/Drift_Test/scan/")
    write_dir.mkdir(exist_ok=True, parents=True)
    name_prefix = "custom_"
    dark_frame = tiffile.imread("dark_frame.tiff")
    #dark_frame = tiffile.imread("dark_frame_hi.tiff")
    shot_frame = tiffile.imread("shot_red00000.tif")
    #shot_frame = tiffile.imread("shot_frame.tiff")

    logging.basicConfig(level=logging.INFO)

    def normalize(image):
        image = image.astype(np.float32)
        minv = image.min()
        maxv = image.max()

        if maxv - minv == 0:
            print("I am skipping normalization")

        norm = (image - minv) / (maxv - minv)
        norm = norm * 255
        norm = norm.astype(np.uint16)

    def main():
        print("Starting Single Exposure Raster Scan:")

        arch_prefix = "x86" if architecture() == 32 else "x64"
        dll_path = Path(__file__).parent / "prior" / arch_prefix / "PriorScientificSDK.dll"
        prior_sdk = PriorSDK(dll_path=dll_path)

        with prior_sdk as sdk_result:
            if not is_successful(sdk_result):
                print(f"CRITICAL: Failed to initialize SDK session: {sdk_result.failure()}")

            controller = sdk_result.unwrap()
            connect_res = controller.connect(stage_com)

            if not is_successful(connect_res):
                print(f"Connection failed: {connect_res.failure()}")

            stage = controller.stage        
            print("Stage connected. Initializing Camera...")

            with dcam:
                camera = dcam[0]
                with camera:
                    camera["image_pixel_type"] = EImagePixelType.MONO16
                    camera[EProp.DIRECTEMGAIN_MODE] = 2
                    camera[EProp.SENSITIVITY] = 255

                    # Set the single exposure time once up front
                    camera["exposure_time"] = exposure_time

                    xsteps = int(width / step)
                    ysteps = int(height / step)
                    nimages = xsteps * ysteps
                    imcount = 0

                    print(f"Total Grid: {xsteps}x{ysteps} ({nimages} positions)")

                    # Maintain original directory naming logic for organizational consistency
                    bracket_dir = write_dir / f"all_bio_withDOE"
                    bracket_dir.mkdir(exist_ok=True, parents=True)

                    for y in range(ysteps):
                        for x in range(xsteps):

                            # --- SINGLE EXPOSURE ACQUISITION BLOCK ---
                            # Capture 1 frame per physical position
                            with Stream(camera, 1) as stream:
                                camera.start()
                                for frame_buffer in stream:
                                    frame = copy_frame(frame_buffer).astype(np.int32)
                                    #mix = np.max(frame)
                                    #diff = dark_frame.astype(np.int32) - shot_frame.astype(np.int32)
                                    #diff = dark_frame.astype(np.int32)
                                    diff = 0
                                    frame = np.array(frame) - diff
                                    #print(f"Max value of image is {mix}")

                                    #frame = np.array(frame) - diff
                                    frame = np.clip(frame, a_min = 1E-12, a_max = None)
                                    #frame = normalize(frame)
                                    frame = frame.astype('uint16')                                    

                                    filename = f"{name_prefix}{imcount:04d}.tiff"
                                    save_path = bracket_dir / filename
                                    tiffile.imwrite(save_path, frame)
                                camera.stop()
                            # -----------------------------

                            imcount += 1

                            # Move stage in X
                            if x < xsteps - 1:
                                slide = stage.move(step, 0)
                                if not is_successful(slide):
                                    print(f"Stage move failed at {stage.position}")

                            # Carriage return at end of row
                            if x == xsteps - 1:
                                xreset = -1 * (xsteps - 1) * step
                                print(f"Row {y+1}/{ysteps} complete. Resetting X, stepping Y.")
                                slide = stage.move(xreset, step)
                                if not is_successful(slide):
                                    print(f"Stage move failed at {stage.position}")

                            time.sleep(0.25)
                        
                    y_return_move = -1 * ysteps * step
                    print(f"Grid scan complete. Returning stage to initial reference position (Stepping Y by {y_return_move} um)...")
                
                    return_slide = stage.move(0, y_return_move)
                    if not is_successful(return_slide):
                        print(f"Return to home position failed at final stage position: {stage.position}")
                    else:
                        print("Stage successfully returned to starting coordinates.")
                    # ---------------------------------    

        print("Scan completed successfully!")
    return (main,)


@app.cell
def _(main):

    if __name__ == "__main__":
        main()
    return


if __name__ == "__main__":
    app.run()
