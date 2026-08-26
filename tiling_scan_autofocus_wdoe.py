import marimo

__generated_with = "0.18.4"
app = marimo.App(width="medium")


@app.cell
def _():
    import time
    import csv
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
    roi_size = 30          

    # Coarse pass: Find the general area quickly
    af_coarse_range = 10.0
    af_coarse_step = 2.0 

    # Fine pass: Nail the exact focus
    af_fine_range = 4.0
    af_fine_step = 0.2

    # EXPOSURE SETTINGS
    exposure_time = 0.020  # Single exposure time in seconds
    pixel_gain = 255

    # --- DIRECTORY SETUP ---
    base_dir = Path("C:/Users/ladmin/OneDrive - University of Utah/grad school/research/Super-Res/Data/06_22_26/Focus_Test/bio/2_stage_scan/red")
    base_dir.mkdir(exist_ok=True, parents=True)

    no_doe_dir = base_dir / "noDOE"
    no_doe_dir.mkdir(exist_ok=True)

    with_doe_dir = base_dir / "withDOE"
    with_doe_dir.mkdir(exist_ok=True)

    csv_path = base_dir / "focus_map.csv"
    name_prefix = "custom_"

    logging.basicConfig(level=logging.INFO)

    def get_roi_focus_score(image, box_size=300):
        """
        Advanced biological focus metric.
        Features: ROI center-of-mass locking, shot-noise pre-smoothing, 
        and structure-targeted normalization.
        """
        img_float = image.astype(np.float64)
        h, w = img_float.shape

        ds = 8
        small = img_float[::ds, ::ds]
        small_blurred = (small[:-1, :-1] + small[1:, :-1] + small[:-1, 1:] + small[1:, 1:]) / 4.0

        max_loc = np.unravel_index(np.argmax(small_blurred), small_blurred.shape)
        center_y, center_x = max_loc[0] * ds, max_loc[1] * ds

        x0 = max(0, min(center_x - box_size // 2, w - box_size))
        y0 = max(0, min(center_y - box_size // 2, h - box_size))
        roi = img_float[y0:y0+box_size, x0:x0+box_size]

        roi_smoothed = (roi[:-1, :-1] + roi[1:, :-1] + roi[:-1, 1:] + roi[1:, 1:]) / 4.0

        threshold = np.percentile(roi_smoothed, 95)
        structure_pixels = roi_smoothed[roi_smoothed >= threshold]

        if len(structure_pixels) == 0:
            return 0.0

        structure_mean = np.mean(structure_pixels)
        if structure_mean < 1.0:
            return 0.0

        lap = (
            -4.0 * roi_smoothed[1:-1, 1:-1] +
            roi_smoothed[:-2, 1:-1] +
            roi_smoothed[2:, 1:-1] +
            roi_smoothed[1:-1, :-2] +
            roi_smoothed[1:-1, 2:]
        )

        return np.var(lap) / structure_mean


    def move_xy_grid(stage, x, y, xsteps, ysteps, step):
        """Helper function to handle grid movement and row resets."""
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


    def main():
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

                    focus_map = {} # Dictionary to store (x, y) -> optimal_z

                    # ==========================================
                    # SCAN 1: AUTOFOCUS & RECORD MAPPING
                    # ==========================================
                    print(f"\n--- STARTING SCAN 1: Topography Mapping ({nimages} positions) ---")
                    imcount = 0
                    for y in range(ysteps):
                        for x in range(xsteps):
                            print(f"\n[Scan 1] Focus & Acquire at Pos (X: {x}, Y: {y})")

                            # --- COARSE SWEEP ---
                            coarse_half = af_coarse_range / 2.0
                            coarse_planes = np.arange(-coarse_half, coarse_half + af_coarse_step, af_coarse_step)
                            best_coarse_score, best_coarse_offset = -1, 0

                            for offset in coarse_planes:
                                piezo.pidevice.MOV(piezo.axis, z_center_start + offset)
                                time.sleep(0.08) 
                                with Stream(camera, 1) as stream:
                                    camera.start()
                                    for frame_buffer in stream:
                                        eval_frame = copy_frame(frame_buffer).astype(np.int32)
                                        score = get_roi_focus_score(eval_frame, box_size=roi_size)
                                        if score > best_coarse_score:
                                            best_coarse_score, best_coarse_offset = score, offset
                                    camera.stop()

                            # --- FINE SWEEP ---
                            fine_center = z_center_start + best_coarse_offset
                            fine_half = af_fine_range / 2.0
                            fine_planes = np.arange(-fine_half, fine_half + af_fine_step, af_fine_step)
                            best_fine_score, optimal_z = -1, fine_center 

                            for offset in fine_planes:
                                target_z = fine_center + offset
                                piezo.pidevice.MOV(piezo.axis, target_z)
                                time.sleep(0.05) 
                                with Stream(camera, 1) as stream:
                                    camera.start()
                                    for frame_buffer in stream:
                                        eval_frame = copy_frame(frame_buffer).astype(np.int32)
                                        score = get_roi_focus_score(eval_frame, box_size=roi_size)
                                        if score > best_fine_score:
                                            best_fine_score, optimal_z = score, target_z
                                    camera.stop()

                            print(f"Optimal Z: {optimal_z:.3f} um")

                            # Store the mapped coordinate
                            focus_map[(x, y)] = optimal_z

                            piezo.pidevice.MOV(piezo.axis, optimal_z)
                            time.sleep(0.12) 

                            # --- IMAGE ACQUISITION ---
                            with Stream(camera, 1) as stream:
                                camera.start()
                                for frame_buffer in stream:
                                    frame = copy_frame(frame_buffer).astype(np.int32)
                                    frame = np.clip(frame, a_min = 1E-12, a_max = None).astype('uint16')                                    
                                    tiffile.imwrite(no_doe_dir / f"{name_prefix}{imcount:04d}.tiff", frame)
                                camera.stop()

                            imcount += 1
                            move_xy_grid(stage, x, y, xsteps, ysteps, step)

                    # --- WRITE CSV LOG ---
                    with open(csv_path, mode='w', newline='') as f:
                        writer = csv.writer(f)
                        writer.writerow(['X_Index', 'Y_Index', 'Z_Position_um'])
                        for (cx, cy), cz in focus_map.items():
                            writer.writerow([cx, cy, f"{cz:.3f}"])
                    print(f"\n[✓] Focus map saved to {csv_path}")

                    # ==========================================
                    # PAUSE FOR USER INPUT
                    # ==========================================
                    print("\n" + "="*50)
                    print("SCAN 1 COMPLETE.")
                    print("="*50)
                    input(">>> PLEASE FLIP THE DOE DOWN. Press [ENTER] when ready to begin Scan 2... <<<")
                    print("="*50)
                
                    # --- HOME STAGES FOR PAUSE ---
                    print("Returning XY stage to origin...")
                    y_return_move = -1 * ysteps * step
                    stage.move(0, y_return_move)
                    time.sleep(0.5)



                    # ==========================================
                    # SCAN 2: HIGH-SPEED ACQUISITION (NO AUTOFOCUS)
                    # ==========================================
                    print(f"\n--- STARTING SCAN 2: DOE Image Capture ({nimages} positions) ---")
                    imcount = 0
                    for y in range(ysteps):
                        for x in range(xsteps):
                            target_z = focus_map[(x, y)]
                            print(f"[Scan 2] Pos (X: {x}, Y: {y}) - Moving directly to Z: {target_z:.3f} um")

                            piezo.pidevice.MOV(piezo.axis, target_z)
                            time.sleep(0.12) # Just enough time for Piezo to settle

                            with Stream(camera, 1) as stream:
                                camera.start()
                                for frame_buffer in stream:
                                    frame = copy_frame(frame_buffer).astype(np.int32)
                                    frame = np.clip(frame, a_min = 1E-12, a_max = None).astype('uint16')                                    
                                    tiffile.imwrite(with_doe_dir / f"{name_prefix}{imcount:04d}.tiff", frame)
                                camera.stop()

                            imcount += 1
                            move_xy_grid(stage, x, y, xsteps, ysteps, step)

                    # --- FINAL CLEANUP ---
                    print("\nGrid scans complete. Cleaning up and homing stages...")
                    stage.move(0, y_return_move)
                    piezo.pidevice.MOV(piezo.axis, z_center_start)
                    time.sleep(0.2)
                    print("[✓] All instruments successfully returned to baseline coordinates.")

        print("Routine completed successfully!")
    return (main,)


@app.cell
def _(main):
    if __name__ == "__main__":
        main() 
    return


if __name__ == "__main__":
    app.run()
