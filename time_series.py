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
    total_frames = 100       # Total number of frames to capture in the time series
    frame_interval = 0     # Target software delay between frames (in seconds)
    stage_com = 3            # Which COM port is the prior stage?

    # EXPOSURE SETTINGS
    exposure_time = 0.020  # Single exposure time in seconds
    pixel_gain = 255

    write_dir = Path("C:/Users/ladmin/OneDrive - University of Utah/grad school/research/Super-Res/Data/06_01_26/Mouse 8/custom_020ms/blue_noDOE/")
    write_dir.mkdir(exist_ok=True, parents=True)
    name_prefix = "Image_"
    dark_frame = tiffile.imread("dark_frame.tiff")
    shot_frame = tiffile.imread("shot_red00000.tif")

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
        print("Starting Single Position Time Series Capture:")

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

            print("Stage connected. Initializing Camera...")

            with dcam:
                camera = dcam[0]
                with camera:
                    camera["image_pixel_type"] = EImagePixelType.MONO16
                    camera[EProp.DIRECTEMGAIN_MODE] = 2
                    camera[EProp.SENSITIVITY] = 255
                    camera["exposure_time"] = exposure_time

                    print(f"Total Sequence: {total_frames} frames (Target Interval: {frame_interval}s)")

                    # Initialize an empty list to hold image arrays in RAM
                    memory_buffer = []

                    print("\n--- ACQUISITION STARTED (Capturing to RAM) ---")
                    start_acq = time.perf_counter()

                    for t in range(total_frames):
                        # --- SINGLE EXPOSURE ACQUISITION BLOCK ---
                        with Stream(camera, 1) as stream:
                            camera.start()
                            for frame_buffer in stream:
                                frame = copy_frame(frame_buffer).astype(np.int32)
                                diff = 0
                                frame = np.array(frame) - diff

                                frame = np.clip(frame, a_min = 1E-12, a_max = None)
                                frame = frame.astype('uint16')                                    

                                # Append the array directly to RAM instead of writing to disk
                                memory_buffer.append(frame)


                        # Software interval timing control between frames
                        if t < total_frames - 1:
                            time.sleep(frame_interval)

                    end_acq = time.perf_counter()
                    print(f"--- ACQUISITION COMPLETE ---")
                    print(f"Captured {len(memory_buffer)} frames in {end_acq - start_acq:.2f} seconds.")

                    # --- POST-ACQUISITION WRITE TO DISK ---
                    print("\nWriting all frames from RAM to disk... Please wait.")
                    series_dir = write_dir
                    series_dir.mkdir(exist_ok=True, parents=True)

                    for t, frame in enumerate(memory_buffer):
                        filename = f"{name_prefix}{t:04d}.tiff"
                        save_path = series_dir / filename
                        tiffile.imwrite(save_path, frame)

                        if (t + 1) % 20 == 0 or (t + 1) == total_frames:
                            print(f"Progress: Saved {t + 1}/{total_frames} frames...")
        #camera.stop()
        print("\nScan completed successfully!")

    if __name__ == "__main__":
        main()    
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
