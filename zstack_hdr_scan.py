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

    from pi.controller import PIStageController

    # --- CONFIGURATION ---
    width = 120  
    height = 120 
    step = 40    
    stage_com = 3   

    # --- Z-STACK PARAMETERS ---
    z_center_start = 198.0  
    z_range = 10.0          
    z_step = 1.25            

    # --- HDR EXPOSURE SETTINGS ---
    # 15ms, 50ms, and 125ms in seconds
    hdr_exposure_times = [0.0139, 0.050, 0.125, 0.25]
    pixel_gain = 255

    # --- DIRECTORY SETUP ---
    base_dir = Path("C:/Users/ladmin/OneDrive - University of Utah/grad school/research/Super-Res/Data/08_26_26/cell5_ND_exp/blue/")
    base_dir.mkdir(exist_ok=True, parents=True)

    no_doe_dir = base_dir / "noDOE"
    no_doe_dir.mkdir(exist_ok=True)

    with_doe_dir = base_dir / "withDOE"
    with_doe_dir.mkdir(exist_ok=True)

    name_prefix = "custom_"
    logging.basicConfig(level=logging.INFO)


    def move_xy_grid(stage, x, y, xsteps, ysteps, step):
        """Helper function to handle grid movement and row resets."""
        if x < xsteps - 1:
            slide = stage.move(step, 0)
            if not is_successful(slide):
                print(f"Stage move failed at {stage.position}")

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

                    xsteps = int(width / step)
                    ysteps = int(height / step)
                    nimages = xsteps * ysteps

                    z_half_range = z_range / 2.0
                    z_planes = np.arange(-z_half_range, z_half_range + z_step, z_step)
                    total_slices = len(z_planes)

                    # Pre-create exposure directories for Scan 1
                    for exp_time in hdr_exposure_times:
                        (no_doe_dir / f"exp_{exp_time}s").mkdir(exist_ok=True, parents=True)

                    # ==========================================
                    # SCAN 1: NO DOE HDR Z-STACKS
                    # ==========================================
                    print(f"\n--- STARTING SCAN 1: Base HDR Z-Stacks ({nimages} positions, {total_slices} slices/pos, {len(hdr_exposure_times)} exposures) ---")
                    imcount = 0
                    for y in range(ysteps):
                        for x in range(xsteps):
                            print(f"[Scan 1] Acquiring HDR Z-Stack at Pos (X: {x}, Y: {y})")

                            # --- Z-STACK ROUTINE ---
                            for z_idx, offset in enumerate(z_planes):
                                target_z = z_center_start + offset
                                piezo.pidevice.MOV(piezo.axis, target_z)
                                time.sleep(0.06)  # Brief settle for piezo

                                # --- HDR MULTI-EXPOSURE CAPTURE ---
                                for exp_time in hdr_exposure_times:
                                    camera["exposure_time"] = exp_time
                                    bracket_dir = no_doe_dir / f"exp_{exp_time}s"

                                    frame = None
                                    with Stream(camera, 1) as stream:
                                        camera.start()
                                        for frame_buffer in stream:
                                            frame = copy_frame(frame_buffer).astype(np.int32)
                                            break
                                        camera.stop()

                                    if frame is None:
                                        print(f"  -> Warning: Dropped frame at Z-index {z_idx}, Exp {exp_time}s. Skipping.")
                                        continue

                                    frame = np.clip(frame, a_min=1E-12, a_max=None).astype('uint16')
                                    filename = f"{name_prefix}p{imcount:04d}_z{z_idx:03d}.tiff"
                                    tiffile.imwrite(bracket_dir / filename, frame)

                            imcount += 1
                            move_xy_grid(stage, x, y, xsteps, ysteps, step)

                    # ==========================================
                    # PAUSE FOR USER INPUT
                    # ==========================================
                    print("\n" + "="*50)
                    print("SCAN 1 COMPLETE.")
                    print("="*50)
                    input(">>> PLEASE FLIP THE DOE DOWN. Press [ENTER] when ready to begin Scan 2... <<<")
                    print("="*50)

                    print("\nReturning XY stage to origin for DOE insertion...")
                    y_return_move = -1 * ysteps * step
                    stage.move(0, y_return_move)
                    time.sleep(0.5)

                    # Pre-create exposure directories for Scan 2
                    for exp_time in hdr_exposure_times:
                        (with_doe_dir / f"exp_{exp_time}s").mkdir(exist_ok=True, parents=True)

                    # ==========================================
                    # SCAN 2: WITH DOE HDR Z-STACKS
                    # ==========================================
                    print(f"\n--- STARTING SCAN 2: DOE HDR Z-Stacks ({nimages} positions, {total_slices} slices/pos, {len(hdr_exposure_times)} exposures) ---")
                    imcount = 0
                    for y in range(ysteps):
                        for x in range(xsteps):
                            print(f"[Scan 2] Acquiring HDR Z-Stack at Pos (X: {x}, Y: {y})")

                            # --- Z-STACK ROUTINE ---
                            for z_idx, offset in enumerate(z_planes):
                                target_z = z_center_start + offset
                                piezo.pidevice.MOV(piezo.axis, target_z)
                                time.sleep(0.06)

                                # --- HDR MULTI-EXPOSURE CAPTURE ---
                                for exp_time in hdr_exposure_times:
                                    camera["exposure_time"] = exp_time
                                    bracket_dir = with_doe_dir / f"exp_{exp_time}s"

                                    frame = None
                                    with Stream(camera, 1) as stream:
                                        camera.start()
                                        for frame_buffer in stream:
                                            frame = copy_frame(frame_buffer).astype(np.int32)
                                            break
                                        camera.stop()

                                    if frame is None:
                                        print(f"  -> Warning: Dropped frame at Z-index {z_idx}, Exp {exp_time}s. Skipping.")
                                        continue

                                    frame = np.clip(frame, a_min=1E-12, a_max=None).astype('uint16')
                                    filename = f"{name_prefix}p{imcount:04d}_z{z_idx:03d}.tiff"
                                    tiffile.imwrite(bracket_dir / filename, frame)

                            imcount += 1
                            move_xy_grid(stage, x, y, xsteps, ysteps, step)

                # --- FINAL CLEANUP ---
                print("\nGrid scans complete. Cleaning up and homing stages...")
                stage.move(0, y_return_move)
                piezo.pidevice.MOV(piezo.axis, z_center_start)
                time.sleep(0.2)
                print("[✓] All instruments successfully returned to baseline coordinates.")

        print("Routine completed successfully!")

    if __name__ == "__main__":
        main()
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
