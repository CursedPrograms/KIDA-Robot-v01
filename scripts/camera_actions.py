# camera_actions.py
import os
import time
from datetime import datetime
import cv2
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FileOutput
import config
import camera_memory

# Directories
IMAGE_DIR = config.IMAGE_DIR
VIDEO_DIR = config.VIDEO_DIR

# Ensure directories exist
os.makedirs(IMAGE_DIR, exist_ok=True)
os.makedirs(VIDEO_DIR, exist_ok=True)

# Camera globals
picam2 = None
recording = False
record_start_time = None
video_filename = None
encoder = None  # keep a reference

# cam_id -> Picamera2 instance ("0" = main cam, 1 = AI/IMX500 cam)
cameras: dict = {}
active_cam_id = 0

# ----------------------------
# Camera setup
# ----------------------------
def set_camera(cam=None, cam_id=0):
    """Initialize the global camera reference and register it under cam_id."""
    global picam2
    if cam is None:
        cam = Picamera2()
        preview_config = cam.create_preview_configuration(
            main={"size": (640, 480), "format": "RGB888"}
        )
        cam.configure(preview_config)
        cam.start()
    cameras[cam_id] = cam
    if cam_id == 0:
        picam2 = cam
    print(f"✅ Camera {cam_id} initialized.")

def cycle_camera() -> int:
    """Switch take_photo() to the next registered camera (for a UI button or voice command)."""
    global active_cam_id
    ids = sorted(cameras.keys())
    if not ids:
        return active_cam_id
    active_cam_id = ids[(ids.index(active_cam_id) + 1) % len(ids)] if active_cam_id in ids else ids[0]
    print(f"🎥 Photo camera set to cam-{active_cam_id}")
    return active_cam_id

def take_photo():
    """Capture a photo from the active camera and save it to IMAGE_DIR."""
    global recording
    if recording:
        print("⚠️ Cannot take photo while recording video.")
        return
    cam = cameras.get(active_cam_id)
    if cam is None:
        print(f"❌ Camera {active_cam_id} not initialized.")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Absolute path — server.py's Flask route resolves relative paths
    # against its own root (scripts/), not the process's CWD, so a
    # relative path here would 404 from the web dashboard.
    filename = os.path.abspath(
        os.path.join(IMAGE_DIR, f"image_cam{active_cam_id}_{timestamp}.jpg")
    )
    try:
        cam.capture_file(filename)
        camera_memory.record_photo(filename)
        print(f"📸 Image saved: {filename}")
        try:
            import daylog
            daylog.note("photo")
        except Exception:
            pass
    except Exception as e:
        print(f"❌ Failed to take photo: {e}")

def save_inference_photo():
    """Export the last YOLO-annotated cam-0 frame to IMAGE_DIR."""
    from camera_threads import get_last_inference_frame
    frame = get_last_inference_frame()
    if frame is None:
        print("⚠️ No inference frame available — turn inference on first.")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.abspath(os.path.join(IMAGE_DIR, f"inference_{timestamp}.jpg"))
    try:
        cv2.imwrite(filename, cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
        camera_memory.record_photo(filename)
        print(f"📸 Inference photo saved: {filename}")
    except Exception as e:
        print(f"❌ Failed to save inference photo: {e}")

# ----------------------------
# Video recording
# ----------------------------
def start_video():
    """Start recording a video if not already recording."""
    global recording, record_start_time, video_filename, encoder

    if recording:
        print("⚠️ Already recording video!")
        return
    if picam2 is None:
        print("❌ Camera not initialized. Call set_camera(cam) first.")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    video_filename = os.path.join(VIDEO_DIR, f"video_{timestamp}.h264")
    encoder = H264Encoder()

    try:
        picam2.start_recording(encoder, FileOutput(video_filename))
        record_start_time = time.time()
        recording = True
        print(f"🎥 Recording video: {video_filename}")
    except Exception as e:
        print(f"❌ Failed to start recording: {e}")
        encoder = None

def stop_video():
    """Stop video recording if currently recording."""
    global recording, encoder

    if not recording:
        print("⚠️ Not currently recording.")
        return
    if picam2 is None:
        print("❌ Camera not initialized. Call set_camera(cam) first.")
        return

    try:
        picam2.stop_recording()
        print(f"✅ Video recording stopped: {video_filename}")
    except Exception as e:
        print(f"❌ Failed to stop recording: {e}")
    finally:
        recording = False
        encoder = None

# ----------------------------
# Automatic recording timeout
# ----------------------------
def check_recording_timeout(timeout=5):
    """Auto-stop recording after `timeout` seconds."""
    global recording, record_start_time
    if recording and (time.time() - record_start_time) >= timeout:
        stop_video()
        print(f"⏱ Auto-stopped video recording after {timeout} seconds.")
