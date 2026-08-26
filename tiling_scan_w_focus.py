import marimo

__generated_with = "0.18.4"
app = marimo.App(width="medium")


@app.cell
def _():
    import time
    import tiffile
    import logging
    import numpy as np
    from pathlib import Path
    from returns.pipeline import is_successful

    # Find and import stage and camera drivers
    from prior.controller import PriorSDK, architecture
    from hamamatsu.hamamatsu.dcam import copy_frame, dcam, Stream, EProp
    from hamamatsu.hamamatsu.dcam import EImagePixelType

    # Import your custom PI wrapper
    from pi.controller import PIStageController

    # --- CONFIGURATION ---
    width = 1000    # Scan width in um
    height = 1000   # scan height in um
    step = 250      # step size in um
    stage_com = 3   # Which COM port is the prior stage?

    # --- AUTOFOCUS PARAMETERS ---
    z_center_start = 198.0  
    roi_size = 300          # INCREASED: Capture the whole diffraction ring structure

    # Coarse pass: Find the general area quickly
    af_coarse_range = 10.0
    af_coarse_step = 2.0 

    # Fine pass: Nail the exact focus
    af_fine_range = 4.0
    af_fine_step = 0.2

    # EXPOSURE SETTINGS
    exposure_time = 0.020  # Single exposure time in seconds
    pixel_gain = 255

    write_dir = Path("C:/Users/ladmin/OneDrive - University of Utah/grad school/research/Super-Res/Data/06_19_26/Focus_Test/hist/bio/")
    write_dir.mkdir(exist_ok=True, parents=True)
    name_prefix = "custom_"

    logging.basicConfig(level=logging.INFO)

    # For beads
    # def get_roi_focus_score(image, box_size=300):
    #     """
    #     Finds focus by maximizing peak intensity (pushing the histogram to the right).
    #     Perfect for point sources like beads, where perfect focus concentrates 
    #     all light into the tightest, brightest possible pixels.
    #     """
    #     img_float = image.astype(np.float64)
    #     h, w = img_float.shape

    #     # Downsample to find the general bright area (avoids single hot pixels)
    #     ds = 8
    #     small = img_float[::ds, ::ds]
    #     max_loc = np.unravel_index(np.argmax(small), small.shape)

    #     # Map back to full-res coordinates
    #     center_y, center_x = max_loc[0] * ds, max_loc[1] * ds

    #     # Crop safely within boundaries
    #     x0 = max(0, min(center_x - box_size // 2, w - box_size))
    #     y0 = max(0, min(center_y - box_size // 2, h - box_size))
    #     roi = img_float[y0:y0+box_size, x0:x0+box_size]

    #     # Return the 99.9th percentile to find the furthest right extent 
    #     # of the histogram while ignoring single-pixel camera noise.
    #     return np.percentile(roi, 99.9)

    # For cells
    # def get_roi_focus_score(image, box_size=10):
    #     """
    #     Focus metric optimized for biological samples and extended objects.
    #     Measures high-frequency spatial contrast (sharpness) using a Laplacian,
    #     normalized by the mean brightness to ensure it tracks sharpness, not sheer intensity.
    #     """
    #     img_float = image.astype(np.float64)
    #     h, w = img_float.shape

    #     # Downsample to find the general bright area of the cell structure
    #     ds = 8
    #     small = img_float[::ds, ::ds]
    #     max_loc = np.unravel_index(np.argmax(small), small.shape)

    #     # Map back to full-res coordinates
    #     center_y, center_x = max_loc[0] * ds, max_loc[1] * ds

    #     # Crop safely within boundaries
    #     x0 = max(0, min(center_x - box_size // 2, w - box_size))
    #     y0 = max(0, min(center_y - box_size // 2, h - box_size))
    #     roi = img_float[y0:y0+box_size, x0:x0+box_size]

    #     roi_mean = np.mean(roi)
    #     if roi_mean < 1.0:  # Avoid division by zero in pitch-black regions
    #         return 0.0

    #     # Apply a 3x3 Laplacian kernel to find sharp edges/textures
    #     lap = (
    #         -4.0 * roi[1:-1, 1:-1] +
    #         roi[:-2, 1:-1] +
    #         roi[2:, 1:-1] +
    #         roi[1:-1, :-2] +
    #         roi[1:-1, 2:]
    #     )

    #     # CRITICAL UPGRADE: Variance of Laplacian divided by the Mean.
    #     # This isolates structural sharpness from bulk fluorescence changes.
    #     return np.var(lap) / roi_mean
    def get_roi_focus_score(image, box_size=10):
        """
        Advanced biological focus metric.
        Features: ROI center-of-mass locking, shot-noise pre-smoothing, 
        and structure-targeted normalization.
        """
        img_float = image.astype(np.float64)
        h, w = img_float.shape

        # --- KNOB 3: Lock the ROI to the center of mass ---
        ds = 8
        small = img_float[::ds, ::ds]
        # Apply a heavy blur to the thumbnail so we find the bulk of the cell, 
        # not a single random bright speck that jumps around during the Z-sweep.
        small_blurred = (small[:-1, :-1] + small[1:, :-1] + small[:-1, 1:] + small[1:, 1:]) / 4.0
    
        max_loc = np.unravel_index(np.argmax(small_blurred), small_blurred.shape)
        center_y, center_x = max_loc[0] * ds, max_loc[1] * ds

        x0 = max(0, min(center_x - box_size // 2, w - box_size))
        y0 = max(0, min(center_y - box_size // 2, h - box_size))
        roi = img_float[y0:y0+box_size, x0:x0+box_size]

        # --- KNOB 1: Pre-smoothing to kill camera shot noise ---
        # Fast 2x2 average pooling (reduces ROI size by 1 pixel in each dimension)
        roi_smoothed = (roi[:-1, :-1] + roi[1:, :-1] + roi[:-1, 1:] + roi[1:, 1:]) / 4.0

        # --- KNOB 2: Smart Normalization ---
        # Find the brightness of the actual cell structure, not the black void
        threshold = np.percentile(roi_smoothed, 95)
        structure_pixels = roi_smoothed[roi_smoothed >= threshold]
    
        if len(structure_pixels) == 0:
            return 0.0
        
        structure_mean = np.mean(structure_pixels)
        if structure_mean < 1.0:
            return 0.0

        # Apply Laplacian to the noise-reduced ROI
        lap = (
            -4.0 * roi_smoothed[1:-1, 1:-1] +
            roi_smoothed[:-2, 1:-1] +
            roi_smoothed[2:, 1:-1] +
            roi_smoothed[1:-1, :-2] +
            roi_smoothed[1:-1, 2:]
        )

        return np.var(lap) / structure_mean

    def main():
        print("Starting Single Exposure Raster Scan with Variance of Laplacian Autofocus:")

        arch_prefix = "x86" if architecture() == 32 else "x64"
        dll_path = Path(__file__).parent / "prior" / arch_prefix / "PriorScientificSDK.dll"
        prior_sdk = PriorSDK(dll_path=dll_path)

        with prior_sdk as sdk_result, PIStageController(dev_name='E-709') as piezo:
            if not is_successful(sdk_result):
                print(f"CRITICAL: Failed to initialize SDK session: {sdk_result.failure()}")
                return

            controller = sdk_result.unwrap()
            connect_res = controller.connect(stage_com)

            if not is_successful(connect_res):
                print(f"Connection failed: {connect_res.failure()}")
                return

            stage = controller.stage        
            print("XY Stage connected.")

            if not piezo.connect():
                print("CRITICAL: Failed to connect to PI Piezo Focus Stage.")
                return

            print(f"Initializing Piezo Focus to target start position: {z_center_start} um")
            piezo.pidevice.MOV(piezo.axis, z_center_start)
            time.sleep(0.5)

            print("Instruments connected. Initializing Camera...")

            with dcam:
                camera = dcam[0]
                with camera:
                    camera["image_pixel_type"] = EImagePixelType.MONO16
                    camera[EProp.DIRECTEMGAIN_MODE] = 2
                    camera[EProp.SENSITIVITY] = 255
                    camera["exposure_time"] = exposure_time

                    xsteps = int(width / step)
                    ysteps = int(height / step)
                    nimages = xsteps * ysteps
                    imcount = 0

                    print(f"Total Grid: {xsteps}x{ysteps} ({nimages} positions)")

                    bracket_dir = write_dir / f"nfov_test_300_2"
                    bracket_dir.mkdir(exist_ok=True, parents=True)

                    for y in range(ysteps):
                        for x in range(xsteps):
                            print(f"\n--- Focus & Acquire at Pos (X: {x}, Y: {y}) ---")

                            # --- AUTOFOCUS: COARSE SWEEP ---
                            coarse_half = af_coarse_range / 2.0
                            coarse_planes = np.arange(-coarse_half, coarse_half + af_coarse_step, af_coarse_step)

                            best_coarse_score = -1
                            best_coarse_offset = 0

                            for offset in coarse_planes:
                                target_z = z_center_start + offset
                                piezo.pidevice.MOV(piezo.axis, target_z)
                                time.sleep(0.08) # Settle window for large steps

                                # CREATE STREAM INSIDE THE LOOP (Fresh iterator every time)
                                with Stream(camera, 1) as stream:
                                    camera.start()
                                    for frame_buffer in stream:
                                        eval_frame = copy_frame(frame_buffer).astype(np.int32)
                                        score = get_roi_focus_score(eval_frame, box_size=roi_size)

                                        if score > best_coarse_score:
                                            best_coarse_score = score
                                            best_coarse_offset = offset
                                    camera.stop()

                            # --- AUTOFOCUS: FINE SWEEP ---
                            fine_center = z_center_start + best_coarse_offset
                            fine_half = af_fine_range / 2.0
                            fine_planes = np.arange(-fine_half, fine_half + af_fine_step, af_fine_step)

                            best_fine_score = -1
                            optimal_z = fine_center # Fallback

                            for offset in fine_planes:
                                target_z = fine_center + offset
                                piezo.pidevice.MOV(piezo.axis, target_z)
                                time.sleep(0.05) # Shorter settle window for small micro-steps

                                # CREATE STREAM INSIDE THE LOOP (Fresh iterator every time)
                                with Stream(camera, 1) as stream:
                                    camera.start()
                                    for frame_buffer in stream:
                                        eval_frame = copy_frame(frame_buffer).astype(np.int32)
                                        score = get_roi_focus_score(eval_frame, box_size=roi_size)

                                        if score > best_fine_score:
                                            best_fine_score = score
                                            optimal_z = target_z
                                    camera.stop()

                            print(f"[Focus Found] Optimal Z: {optimal_z:.3f} um (Score: {best_fine_score:.2f})")
                            piezo.pidevice.MOV(piezo.axis, optimal_z)
                            time.sleep(0.12) # Final settle before final image capture

                            # --- FINAL IMAGE ACQUISITION ---
                            with Stream(camera, 1) as stream:
                                camera.start()
                                for frame_buffer in stream:
                                    frame = copy_frame(frame_buffer).astype(np.int32)
                                    frame = np.clip(frame, a_min = 1E-12, a_max = None)
                                    frame = frame.astype('uint16')                                    

                                    filename = f"{name_prefix}{imcount:04d}.tiff"
                                    save_path = bracket_dir / filename
                                    tiffile.imwrite(save_path, frame)
                                camera.stop()

                            imcount += 1

                            # Move XY stage in X
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

                    # --- RETURN ALL AXES TO STARTING COORDINATES ---
                    print("\n==================================================")
                    print("Grid scan complete. Cleaning up and homing stages...")

                    y_return_move = -1 * ysteps * step
                    print(f"[>] Returning XY stage (Stepping Y by {y_return_move} um)...")
                    return_slide = stage.move(0, y_return_move)

                    print(f"[>] Returning Piezo stage back to initial position: {z_center_start} um...")
                    piezo.pidevice.MOV(piezo.axis, z_center_start)
                    time.sleep(0.2)

                    if not is_successful(return_slide):
                        print(f"[-] XY Return to home position failed at: {stage.position}")
                    else:
                        print("[✓] All instruments successfully returned to baseline coordinates.")
                    print("==================================================")

        print("Scan completed successfully!")
    return (main,)


@app.cell
def _(main):

    if __name__ == "__main__":
        main() 
    return


if __name__ == "__main__":
    app.run()
