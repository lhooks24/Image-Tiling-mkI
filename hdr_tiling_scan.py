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
    width = 1250    # Scan width in um
    height = 1250   # scan height in um
    step = 25      # step size in um
    stage_com = 3   # Which COM port is the prior stage?

    # HDR SETTINGS
    exposure_times = [0.015, 0.030, 0.060, 0.120, 0.240] 
    pixel_gain = 255

    write_dir = Path("./scans/02_24_26/both/withDOE")
    write_dir.mkdir(exist_ok=True, parents=True)
    name_prefix = "custom_"
    dark_frame = tiffile.imread("dark_frame.tiff")
    #dark_frame = tiffile.imread("dark_frame_hi.tiff")
    shot_frame = tiffile.imread("red_dark.tif")
    #shot_frame = tiffile.imread("shot_frame.tiff")

    logging.basicConfig(level=logging.INFO)
        
    def main():
        print("Starting HDR Raster Scan:")

        arch_prefix = "x86" if architecture() == 32 else "x64"
        dll_path = Path(__file__).parent / "prior" / arch_prefix / "PriorScientificSDK.dll"
        prior_sdk = PriorSDK(dll_path=dll_path)

        with prior_sdk as sdk_result:
            if not is_successful(sdk_result):
                print(f"CRITICAL: Failed to initialize SDK session: {sdk_result.failure()}")
                return

            controller = sdk_result.unwrap()
            connect_res = controller.connect(stage_com)

            if not is_successful(connect_res):
                print(f"Connection failed: {connect_res.failure()}")
                return

            stage = controller.stage        
            print("Stage connected. Initializing Camera...")

            with dcam:
                camera = dcam[0]
                with camera:
                    camera["image_pixel_type"] = EImagePixelType.MONO16
                    camera[EProp.DIRECTEMGAIN_MODE] = 2
                    camera[EProp.SENSITIVITY] = 255

                    xsteps = int(width / step)
                    ysteps = int(height / step)
                    nimages = xsteps * ysteps
                    imcount = 0

                    print(f"Total Grid: {xsteps}x{ysteps} ({nimages} positions)")

                    for y in range(ysteps):
                        for x in range(xsteps):

                            # --- HDR ACQUISITION BLOCK ---
                            # For every physical position, take multiple exposures
                            for exp_time in exposure_times:
                                # 1. Update Exposure
                                camera["exposure_time"] = exp_time
                        

                                # 2. Define path: write_dir / exp_0.01s / custom_0001.tiff
                                bracket_dir = write_dir / f"exp_{exp_time}s"
                                bracket_dir.mkdir(exist_ok=True)

                                # 3. Capture Frame
                                # We use a stream of 1 because we are at a single position
                                with Stream(camera, 1) as stream:
                                    camera.start()
                                    for frame_buffer in stream:
                                        frame = copy_frame(frame_buffer).astype(np.int32)
                                        mix = np.max(frame)
                                        diff = dark_frame.astype(np.int32) - shot_frame.astype(np.int32)
                                        frame = np.array(frame) - diff
                                        #print(f"Max value of image is {mix}")

                                        #frame = np.array(frame) - diff
                                        frame = np.clip(frame, a_min = 1E-12, a_max = None)
                                        #frame = cv2.normalize(frame, None, 255, 255, cv2.NORM_INF, dtype=cv2.CV_8U)
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
                                    return

                            # Carriage return at end of row
                            if x == xsteps - 1:
                                xreset = -1 * (xsteps - 1) * step
                                print(f"Row {y+1}/{ysteps} complete. Resetting X, stepping Y.")
                                slide = stage.move(xreset, step)
                                if not is_successful(slide):
                                    print(f"Stage move failed at {stage.position}")
                                    return

                            time.sleep(0.25)

        print("Scan completed successfully!")

    if __name__ == "__main__":
        main()
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
