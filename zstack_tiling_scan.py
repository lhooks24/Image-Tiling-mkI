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
    width = 1080  
    height = 1080 
    # width = 70
    # height = 70
    step = 40   
    # step = 105
    stage_com = 3   

    # --- Z-STACK PARAMETERS ---
    z_center_start = 198.0  
    z_range = 10.0          
    z_step = 1.25            

    # --- EXPOSURE SETTINGS ---
    USE_AUTO_EXPOSURE = False    # Set to False for fixed exposure, True for variable exposure
    FIXED_EXPOSURE_TIME = 0.050 # Fixed exposure time in seconds (used when USE_AUTO_EXPOSURE = False)

    BASE_EXPOSURE = 0.020        # Baseline single exposure time for auto-exposure (seconds)
    MAX_EXPOSURE_TIME = 0.250    # Hard cap to protect scan time (seconds)
    TARGET_INTENSITY = 62000     # Target ADU for auto-exposure (max 65535)
    pixel_gain = 255

    # --- DIRECTORY SETUP ---
    base_dir = Path("C:/Users/ladmin/OneDrive - University of Utah/grad school/research/Super-Res/Data/07_21_26/survey_green")
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


    def determine_exposure(camera, piezo):
        """Sets fixed exposure or calculates auto-exposure based on configuration."""
        if not USE_AUTO_EXPOSURE:
            camera["exposure_time"] = FIXED_EXPOSURE_TIME
            print(f"  -> Fixed exposure: {FIXED_EXPOSURE_TIME * 1000:.1f}ms")
            return FIXED_EXPOSURE_TIME

        # --- AUTO-EXPOSURE ROUTINE ---
        piezo.pidevice.MOV(piezo.axis, z_center_start)
        time.sleep(0.06) 

        camera["exposure_time"] = BASE_EXPOSURE
        preview_frame = None

        with Stream(camera, 1) as stream:
            camera.start()
            for frame_buffer in stream:
                preview_frame = copy_frame(frame_buffer)
                break  # Prevent hanging
            camera.stop()

        if preview_frame is not None:
            # Isolate the center 350x350 pixels
            h, w = preview_frame.shape
            cy, cx = h // 2, w // 2
            center_crop = preview_frame[max(0, cy - 175):cy + 175, max(0, cx - 175):cx + 175]

            p99 = np.percentile(center_crop, 99.9)
            if p99 > 100:
                scaling_factor = TARGET_INTENSITY / p99
                new_exp = min(BASE_EXPOSURE * scaling_factor, MAX_EXPOSURE_TIME)
            else:
                new_exp = MAX_EXPOSURE_TIME
        else:
            print("Warning: Failed to capture preview frame. Defaulting to max exposure.")
            new_exp = MAX_EXPOSURE_TIME

        camera["exposure_time"] = new_exp
        print(f"  -> Optimized auto-exposure: {new_exp * 1000:.1f}ms")
        return new_exp


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

                    # ==========================================
                    # SCAN 1: NO DOE Z-STACKS
                    # ==========================================
                    print(f"\n--- STARTING SCAN 1: Base Z-Stacks ({nimages} positions, {total_slices} slices/pos) ---")
                    imcount = 0
                    for y in range(ysteps):
                        for x in range(xsteps):
                            print(f"[Scan 1] Acquiring Z-Stack at Pos (X: {x}, Y: {y})")

                            # Determine and set exposure time
                            determine_exposure(camera, piezo)

                            # --- Z-STACK ROUTINE ---
                            for z_idx, offset in enumerate(z_planes):
                                target_z = z_center_start + offset
                                piezo.pidevice.MOV(piezo.axis, target_z)
                                time.sleep(0.06) # Brief settle for piezo

                                frame = None

                                with Stream(camera, 1) as stream:
                                    camera.start()
                                    for frame_buffer in stream:
                                        frame = copy_frame(frame_buffer).astype(np.int32)
                                        break
                                    camera.stop()

                                if frame is None:
                                    print(f"  -> Warning: Dropped frame at Z-index {z_idx}. Skipping slice.")
                                    continue

                                frame = np.clip(frame, a_min=1E-12, a_max=None).astype('uint16')
                                filename = f"{name_prefix}p{imcount:04d}_z{z_idx:03d}.tiff"
                                tiffile.imwrite(no_doe_dir / filename, frame)

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

                    # ==========================================
                    # SCAN 2: WITH DOE Z-STACKS
                    # ==========================================
                    print(f"\n--- STARTING SCAN 2: DOE Z-Stacks ({nimages} positions, {total_slices} slices/pos) ---")
                    imcount = 0
                    for y in range(ysteps):
                        for x in range(xsteps):
                            print(f"[Scan 2] Acquiring Z-Stack at Pos (X: {x}, Y: {y})")

                            # Determine and set exposure time
                            determine_exposure(camera, piezo)

                            # --- Z-STACK ROUTINE ---
                            for z_idx, offset in enumerate(z_planes):
                                target_z = z_center_start + offset
                                piezo.pidevice.MOV(piezo.axis, target_z)
                                time.sleep(0.06) 

                                frame = None
                                with Stream(camera, 1) as stream:
                                    camera.start()
                                    for frame_buffer in stream:
                                        frame = copy_frame(frame_buffer).astype(np.int32)
                                        break
                                    camera.stop()

                                if frame is None:
                                    print(f"  -> Warning: Dropped frame at Z-index {z_idx}. Skipping slice.")
                                    continue

                                frame = np.clip(frame, a_min=1E-12, a_max=None).astype('uint16')
                                filename = f"{name_prefix}p{imcount:04d}_z{z_idx:03d}.tiff"
                                tiffile.imwrite(with_doe_dir / filename, frame)

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
    # import time
    # import tiffile
    # import logging
    # import numpy as np
    # from pathlib import Path
    # from returns.pipeline import is_successful

    # # Find and import stage and camera drivers
    # from prior.controller import PriorSDK, architecture
    # from hamamatsu.hamamatsu.dcam import copy_frame, dcam, Stream, EProp
    # from hamamatsu.hamamatsu.dcam import EImagePixelType

    # from pi.controller import PIStageController

    # # --- CONFIGURATION ---
    # width = 1050  
    # height = 1050  
    # step = 35      
    # stage_com = 3   

    # # --- Z-STACK PARAMETERS ---
    # z_center_start = 198.0  
    # z_range = 10.0          
    # z_step = 1.0            

    # # --- EXPOSURE SETTINGS ---
    # BASE_EXPOSURE = 0.020       # Baseline single exposure time (seconds)
    # MAX_EXPOSURE_TIME = 0.250   # Hard cap to protect scan time (seconds)
    # TARGET_INTENSITY = 62000    # Target ADU for auto-exposure (max 65535)
    # pixel_gain = 255

    # # --- DIRECTORY SETUP ---
    # base_dir = Path("C:/Users/ladmin/OneDrive - University of Utah/grad school/research/Super-Res/Data/07_21_26/test")
    # base_dir.mkdir(exist_ok=True, parents=True)

    # no_doe_dir = base_dir / "noDOE"
    # no_doe_dir.mkdir(exist_ok=True)

    # with_doe_dir = base_dir / "withDOE"
    # with_doe_dir.mkdir(exist_ok=True)

    # name_prefix = "custom_"
    # logging.basicConfig(level=logging.INFO)

    # def move_xy_grid(stage, x, y, xsteps, ysteps, step):
    #     """Helper function to handle grid movement and row resets."""
    #     if x < xsteps - 1:
    #         slide = stage.move(step, 0)
    #         if not is_successful(slide):
    #             print(f"Stage move failed at {stage.position}")

    #     if x == xsteps - 1:
    #         xreset = -1 * (xsteps - 1) * step
    #         print(f"Row {y+1}/{ysteps} complete. Resetting X, stepping Y.")
    #         slide = stage.move(xreset, step)
    #         if not is_successful(slide):
    #             print(f"Stage move failed at {stage.position}")
    #     time.sleep(0.25)


    # def main():
    #     arch_prefix = "x86" if architecture() == 32 else "x64"
    #     dll_path = Path(__file__).parent / "prior" / arch_prefix / "PriorScientificSDK.dll"
    #     prior_sdk = PriorSDK(dll_path=dll_path)

    #     with prior_sdk as sdk_result, PIStageController(dev_name='E-709') as piezo:
    #         if not is_successful(sdk_result):
    #             print(f"CRITICAL: Failed to initialize SDK session: {sdk_result.failure()}")
    #             return

    #         controller = sdk_result.unwrap()
    #         connect_res = controller.connect(stage_com)

    #         if not is_successful(connect_res):
    #             print(f"Connection failed: {connect_res.failure()}")
    #             return

    #         stage = controller.stage        
    #         print("XY Stage connected.")

    #         if not piezo.connect():
    #             print("CRITICAL: Failed to connect to PI Piezo Focus Stage.")
    #             return

    #         print(f"Initializing Piezo Focus to target start position: {z_center_start} um")
    #         piezo.pidevice.MOV(piezo.axis, z_center_start)
    #         time.sleep(0.5)

    #         with dcam:
    #             camera = dcam[0]
    #             with camera:
    #                 camera["image_pixel_type"] = EImagePixelType.MONO16
    #                 camera[EProp.DIRECTEMGAIN_MODE] = 2
    #                 camera[EProp.SENSITIVITY] = 255

    #                 xsteps = int(width / step)
    #                 ysteps = int(height / step)
    #                 nimages = xsteps * ysteps

    #                 z_half_range = z_range / 2.0
    #                 z_planes = np.arange(-z_half_range, z_half_range + z_step, z_step)
    #                 total_slices = len(z_planes)

    #                 # ==========================================
    #                 # SCAN 1: NO DOE Z-STACKS
    #                 # ==========================================
    #                 print(f"\n--- STARTING SCAN 1: Base Z-Stacks ({nimages} positions, {total_slices} slices/pos) ---")
    #                 imcount = 0
    #                 for y in range(ysteps):
    #                     for x in range(xsteps):
    #                         print(f"[Scan 1] Acquiring Z-Stack at Pos (X: {x}, Y: {y})")

    #                         # --- AUTO-EXPOSURE ROUTINE ---
    #                         piezo.pidevice.MOV(piezo.axis, z_center_start)
    #                         time.sleep(0.06) 

    #                         camera["exposure_time"] = BASE_EXPOSURE
    #                         preview_frame = None

    #                         with Stream(camera, 1) as stream:
    #                             camera.start()
    #                             for frame_buffer in stream:
    #                                 preview_frame = copy_frame(frame_buffer)
    #                                 break  # Prevent hanging
    #                             camera.stop()

    #                         if preview_frame is not None:
    #                             # Isolate the center 350x350 pixels
    #                             h, w = preview_frame.shape
    #                             cy, cx = h // 2, w // 2
    #                             center_crop = preview_frame[max(0, cy - 175):cy + 175, max(0, cx - 175):cx + 175]

    #                             p99 = np.percentile(center_crop, 99.9)
    #                             if p99 > 100:
    #                                 scaling_factor = TARGET_INTENSITY / p99
    #                                 new_exp = min(BASE_EXPOSURE * scaling_factor, MAX_EXPOSURE_TIME)
    #                             else:
    #                                 new_exp = MAX_EXPOSURE_TIME
    #                         else:
    #                             print("Warning: Failed to capture preview frame. Defaulting to max exposure.")
    #                             new_exp = MAX_EXPOSURE_TIME

    #                         camera["exposure_time"] = new_exp
    #                         print(f"  -> Optimized exposure: {new_exp*1000:.1f}ms")
    #                         # -----------------------------

    #                         # --- Z-STACK ROUTINE ---
    #                         for z_idx, offset in enumerate(z_planes):
    #                             target_z = z_center_start + offset
    #                             piezo.pidevice.MOV(piezo.axis, target_z)
    #                             time.sleep(0.06) # Brief settle for piezo

    #                             frame = None

    #                             with Stream(camera, 1) as stream:
    #                                 camera.start()
    #                                 for frame_buffer in stream:
    #                                     frame = copy_frame(frame_buffer).astype(np.int32)
    #                                     break
    #                                 camera.stop()

    #                             if frame is None:
    #                                 print(f"  -> Warning: Dropped frame at Z-index {z_idx}. Skipping slice.")
    #                                 continue

    #                             frame = np.clip(frame, a_min=1E-12, a_max=None).astype('uint16')
    #                             filename = f"{name_prefix}p{imcount:04d}_z{z_idx:03d}.tiff"
    #                             tiffile.imwrite(no_doe_dir / filename, frame)

    #                         imcount += 1
    #                         move_xy_grid(stage, x, y, xsteps, ysteps, step)

    #                 # ==========================================
    #                 # PAUSE FOR USER INPUT
    #                 # ==========================================
    #                 print("\n" + "="*50)
    #                 print("SCAN 1 COMPLETE.")
    #                 print("="*50)
    #                 input(">>> PLEASE FLIP THE DOE DOWN. Press [ENTER] when ready to begin Scan 2... <<<")
    #                 print("="*50)

    #                 print("\nReturning XY stage to origin for DOE insertion...")
    #                 y_return_move = -1 * ysteps * step
    #                 stage.move(0, y_return_move)
    #                 time.sleep(0.5)

    #                 # ==========================================
    #                 # SCAN 2: WITH DOE Z-STACKS
    #                 # ==========================================
    #                 print(f"\n--- STARTING SCAN 2: DOE Z-Stacks ({nimages} positions, {total_slices} slices/pos) ---")
    #                 imcount = 0
    #                 for y in range(ysteps):
    #                     for x in range(xsteps):
    #                         print(f"[Scan 2] Acquiring Z-Stack at Pos (X: {x}, Y: {y})")

    #                         # --- AUTO-EXPOSURE ROUTINE ---
    #                         piezo.pidevice.MOV(piezo.axis, z_center_start)
    #                         time.sleep(0.06) 

    #                         camera["exposure_time"] = BASE_EXPOSURE
    #                         preview_frame = None

    #                         with Stream(camera, 1) as stream:
    #                             camera.start()
    #                             for frame_buffer in stream:
    #                                 preview_frame = copy_frame(frame_buffer)
    #                                 break
    #                             camera.stop()

    #                         if preview_frame is not None:
    #                             # Isolate the center 350x350 pixels
    #                             h, w = preview_frame.shape
    #                             cy, cx = h // 2, w // 2
    #                             center_crop = preview_frame[max(0, cy - 175):cy + 175, max(0, cx - 175):cx + 175]

    #                             p99 = np.percentile(center_crop, 99.9)
    #                             if p99 > 100:
    #                                 scaling_factor = TARGET_INTENSITY / p99
    #                                 new_exp = min(BASE_EXPOSURE * scaling_factor, MAX_EXPOSURE_TIME)
    #                             else:
    #                                 new_exp = MAX_EXPOSURE_TIME
    #                         else:
    #                             new_exp = MAX_EXPOSURE_TIME

    #                         camera["exposure_time"] = new_exp
    #                         print(f"  -> Optimized exposure: {new_exp*1000:.1f}ms")
    #                         # -----------------------------

    #                         # --- Z-STACK ROUTINE ---
    #                         for z_idx, offset in enumerate(z_planes):
    #                             target_z = z_center_start + offset
    #                             piezo.pidevice.MOV(piezo.axis, target_z)
    #                             time.sleep(0.06) 

    #                             frame = None
    #                             with Stream(camera, 1) as stream:
    #                                 camera.start()
    #                                 for frame_buffer in stream:
    #                                     frame = copy_frame(frame_buffer).astype(np.int32)
    #                                     break
    #                                 camera.stop()

    #                             if frame is None:
    #                                 print(f"  -> Warning: Dropped frame at Z-index {z_idx}. Skipping slice.")
    #                                 continue

    #                             frame = np.clip(frame, a_min=1E-12, a_max=None).astype('uint16')
    #                             filename = f"{name_prefix}p{imcount:04d}_z{z_idx:03d}.tiff"
    #                             tiffile.imwrite(with_doe_dir / filename, frame)

    #                         imcount += 1
    #                         move_xy_grid(stage, x, y, xsteps, ysteps, step)

    #             # --- FINAL CLEANUP ---
    #             print("\nGrid scans complete. Cleaning up and homing stages...")
    #             stage.move(0, y_return_move)
    #             piezo.pidevice.MOV(piezo.axis, z_center_start)
    #             time.sleep(0.2)
    #             print("[✓] All instruments successfully returned to baseline coordinates.")

    #     print("Routine completed successfully!")

    # if __name__ == "__main__":
    #     main()
    return


@app.cell
def _():
    # import time
    # import tiffile
    # import logging
    # import numpy as np
    # from pathlib import Path
    # from returns.pipeline import is_successful

    # # Find and import stage and camera drivers
    # from prior.controller import PriorSDK, architecture
    # from hamamatsu.hamamatsu.dcam import copy_frame, dcam, Stream, EProp
    # from hamamatsu.hamamatsu.dcam import EImagePixelType

    # # Import your custom PI wrapper
    # from pi.controller import PIStageController

    # # --- CONFIGURATION ---
    # width = 1225   # Scan width in um
    # height = 1225   # scan height in um
    # step = 35      # step size in um
    # stage_com = 3   # Which COM port is the prior stage?

    # # --- Z-STACK PARAMETERS ---
    # z_center_start = 198.0  
    # z_range = 10.0          # Total Z travel per stack in um
    # z_step = 1.0            # Distance between Z slices in um

    # # EXPOSURE SETTINGS
    # exposure_time = 0.020   # Single exposure time in seconds
    # pixel_gain = 255

    # # --- DIRECTORY SETUP ---
    # base_dir = Path("C:/Users/ladmin/OneDrive - University of Utah/grad school/research/Super-Res/Data/07_01_26/all")
    # base_dir.mkdir(exist_ok=True, parents=True)

    # no_doe_dir = base_dir / "noDOE"
    # no_doe_dir.mkdir(exist_ok=True)

    # with_doe_dir = base_dir / "withDOE"
    # with_doe_dir.mkdir(exist_ok=True)

    # name_prefix = "custom_"

    # logging.basicConfig(level=logging.INFO)

    # def move_xy_grid(stage, x, y, xsteps, ysteps, step):
    #     """Helper function to handle grid movement and row resets."""
    #     # Move XY stage in X
    #     if x < xsteps - 1:
    #         slide = stage.move(step, 0)
    #         if not is_successful(slide):
    #             print(f"Stage move failed at {stage.position}")

    #     # Carriage return at end of row
    #     if x == xsteps - 1:
    #         xreset = -1 * (xsteps - 1) * step
    #         print(f"Row {y+1}/{ysteps} complete. Resetting X, stepping Y.")
    #         slide = stage.move(xreset, step)
    #         if not is_successful(slide):
    #             print(f"Stage move failed at {stage.position}")
    #     time.sleep(0.25)


    # def main():
    #     arch_prefix = "x86" if architecture() == 32 else "x64"
    #     dll_path = Path(__file__).parent / "prior" / arch_prefix / "PriorScientificSDK.dll"
    #     prior_sdk = PriorSDK(dll_path=dll_path)

    #     with prior_sdk as sdk_result, PIStageController(dev_name='E-709') as piezo:
    #         if not is_successful(sdk_result):
    #             print(f"CRITICAL: Failed to initialize SDK session: {sdk_result.failure()}")
    #             return

    #         controller = sdk_result.unwrap()
    #         connect_res = controller.connect(stage_com)

    #         if not is_successful(connect_res):
    #             print(f"Connection failed: {connect_res.failure()}")
    #             return

    #         stage = controller.stage        
    #         print("XY Stage connected.")

    #         if not piezo.connect():
    #             print("CRITICAL: Failed to connect to PI Piezo Focus Stage.")
    #             return

    #         print(f"Initializing Piezo Focus to target start position: {z_center_start} um")
    #         piezo.pidevice.MOV(piezo.axis, z_center_start)
    #         time.sleep(0.5)

    #         with dcam:
    #             camera = dcam[0]
    #             with camera:
    #                 camera["image_pixel_type"] = EImagePixelType.MONO16
    #                 camera[EProp.DIRECTEMGAIN_MODE] = 2
    #                 camera[EProp.SENSITIVITY] = 255
    #                 camera["exposure_time"] = exposure_time

    #                 xsteps = int(width / step)
    #                 ysteps = int(height / step)
    #                 nimages = xsteps * ysteps

    #                 # Calculate Z-planes once
    #                 z_half_range = z_range / 2.0
    #                 z_planes = np.arange(-z_half_range, z_half_range + z_step, z_step)
    #                 total_slices = len(z_planes)

    #                 # ==========================================
    #                 # SCAN 1: NO DOE Z-STACKS
    #                 # ==========================================
    #                 print(f"\n--- STARTING SCAN 1: Base Z-Stacks ({nimages} positions, {total_slices} slices/pos) ---")
    #                 imcount = 0
    #                 for y in range(ysteps):
    #                     for x in range(xsteps):
    #                         print(f"[Scan 1] Acquiring Z-Stack at Pos (X: {x}, Y: {y})")

    #                         for z_idx, offset in enumerate(z_planes):
    #                             target_z = z_center_start + offset
    #                             piezo.pidevice.MOV(piezo.axis, target_z)
    #                             time.sleep(0.06) # Brief settle for piezo

    #                             with Stream(camera, 1) as stream:
    #                                 camera.start()
    #                                 for frame_buffer in stream:
    #                                     frame = copy_frame(frame_buffer).astype(np.int32)
    #                                     frame = np.clip(frame, a_min=1E-12, a_max=None).astype('uint16')

    #                                     # Save with position and slice index
    #                                     filename = f"{name_prefix}p{imcount:04d}_z{z_idx:03d}.tiff"
    #                                     tiffile.imwrite(no_doe_dir / filename, frame)
    #                                 camera.stop()

    #                         imcount += 1
    #                         move_xy_grid(stage, x, y, xsteps, ysteps, step)

    #                 # ==========================================
    #                 # PAUSE FOR USER INPUT
    #                 # ==========================================
    #                 print("\n" + "="*50)
    #                 print("SCAN 1 COMPLETE.")
    #                 print("="*50)
    #                 input(">>> PLEASE FLIP THE DOE DOWN. Press [ENTER] when ready to begin Scan 2... <<<")
    #                 print("="*50)

    #                 # --- HOME STAGES FOR PAUSE ---
    #                 print("\nReturning XY stage to origin for DOE insertion...")
    #                 y_return_move = -1 * ysteps * step
    #                 stage.move(0, y_return_move)
    #                 time.sleep(0.5)

    #                 # ==========================================
    #                 # SCAN 2: WITH DOE Z-STACKS
    #                 # ==========================================
    #                 print(f"\n--- STARTING SCAN 2: DOE Z-Stacks ({nimages} positions, {total_slices} slices/pos) ---")
    #                 imcount = 0
    #                 for y in range(ysteps):
    #                     for x in range(xsteps):
    #                         print(f"[Scan 2] Acquiring Z-Stack at Pos (X: {x}, Y: {y})")

    #                         for z_idx, offset in enumerate(z_planes):
    #                             target_z = z_center_start + offset
    #                             piezo.pidevice.MOV(piezo.axis, target_z)
    #                             time.sleep(0.06) 

    #                             with Stream(camera, 1) as stream:
    #                                 camera.start()
    #                                 for frame_buffer in stream:
    #                                     frame = copy_frame(frame_buffer).astype(np.int32)
    #                                     frame = np.clip(frame, a_min=1E-12, a_max=None).astype('uint16')                                    

    #                                     filename = f"{name_prefix}p{imcount:04d}_z{z_idx:03d}.tiff"
    #                                     tiffile.imwrite(with_doe_dir / filename, frame)
    #                                 camera.stop()

    #                         imcount += 1
    #                         move_xy_grid(stage, x, y, xsteps, ysteps, step)

    #                 # --- FINAL CLEANUP ---
    #                 print("\nGrid scans complete. Cleaning up and homing stages...")
    #                 stage.move(0, y_return_move)
    #                 piezo.pidevice.MOV(piezo.axis, z_center_start)
    #                 time.sleep(0.2)
    #                 print("[✓] All instruments successfully returned to baseline coordinates.")

    #     print("Routine completed successfully!")
    return


@app.cell
def _():
    # if __name__ == "__main__":
    #     main() 
    return


if __name__ == "__main__":
    app.run()
