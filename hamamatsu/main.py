import logging
import cv2
import tiffile
from pathlib import Path
from hamamatsu.dcam import copy_frame, dcam, Stream

logging.basicConfig(level=logging.INFO)
output_dir = Path("./acquired_frames")
output_dir.mkdir(exist_ok=True)
with dcam:
    camera = dcam[0]
    with camera:
        print(camera.info)
        print(camera['image_width'].value, camera['image_height'].value)
        camera.is_open
        # Simple acquisition example
        nb_frames = 10
        camera["exposure_time"] = 0.1
        with Stream(camera, nb_frames) as stream:
                logging.info("start acquisition")
                camera.start()
                for i, frame_buffer in enumerate(stream):
                    frame = copy_frame(frame_buffer)
                    frame = frame.astype('uint16')
                    frame = cv2.normalize(frame, None, 0, 65535, cv2.NORM_MINMAX) # scale to full uint16 range
                    logging.info(f"acquired frame #%d/%d", i+1, nb_frames)
                    tiffile.imwrite(output_dir / f"frame_{i:03d}.tiff", frame)
                    
                logging.info("finished acquisition")