# lane_detect_mode.py — Hailo UFLD_v2 live lane-following drive mode
#
# Runs live lane detection on cam-1's always-on feed (the same
# non-contending accessor face_emotion_mode.py uses, so this never fights
# cam-0's YOLO loop or its inference on/off toggle) and steers dev00 to
# keep the robot centered between the detected lane boundaries.
#
# Model + coordinate math ported from scripts/python/lane_detection/
# (Hailo's UFLD_v2 example — originally an offline batch/video-file
# pipeline using multiprocessing + HailoAsyncInference). This thread
# instead runs the same model synchronously, one live frame at a time, the
# same low-level VDevice pattern face_emotion_mode.py's _FaceDetector uses
# (HailoSchedulingAlgorithm.ROUND_ROBIN + multi_process_service +
# group_id="SHARED" so HailoRT interleaves it with the Whisper STT
# pipeline and face-emotion detection rather than fighting them for the
# Hailo-8L). UFLDProcessing itself (resize/decode math) is reused
# unchanged from lane_detection_utils.py.
#
# arduino00.ino only understands FORWARD/BACKWARD/LEFT/RIGHT/STOP — no
# gentle "slight turn" commands — so steering is bucketed into those four,
# same as line_follow_mode.py.
#
# ⚠️ Untested on a real track: the offset→command thresholds below
# (CENTER_DEADBAND_PX, TURN_PX) are a reasonable starting guess, not
# measured against real hardware/footage. Expect to tune them once you can
# actually run the robot on a lane.

import sys
import threading
import time
import logging
from pathlib import Path

import cv2
import numpy as np
from hailo_platform import HEF, VDevice, HailoSchedulingAlgorithm, FormatType

import camera_threads
import state
from arduino import send_command

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent / "python" / "lane_detection"))
from lane_detection_utils import UFLDProcessing  # noqa: E402

logger = logging.getLogger(__name__)

LANE_HEF = str(BASE_DIR / "resources" / "hefs" / "ufld_v2_tu.hef")

# ufld_v2_tu/input_layer1 is (320, 800, 3) — (height, width, channels)
MODEL_INPUT_H = 320
MODEL_INPUT_W = 800

LOOP_DELAY          = 0.05   # seconds between steering updates (matches line_follow_mode)
CENTER_DEADBAND_PX  = 40     # |offset| within this many px of frame-center -> FORWARD
LOST_LANE_TIMEOUT_S = 0.5    # stop once the lane's been unreadable this long

_stop_event = threading.Event()
_thread: threading.Thread | None = None


class _LaneDetector:
    """Owns one shared-group VDevice for ufld_v2_tu — lazily created so
    importing this module doesn't touch the Hailo-8 until the mode starts."""

    def __init__(self):
        self.hef = HEF(LANE_HEF)
        params = VDevice.create_params()
        params.scheduling_algorithm = HailoSchedulingAlgorithm.ROUND_ROBIN
        params.multi_process_service = True
        params.group_id = "SHARED"
        self.target = VDevice(params)
        self.infer_model = self.target.create_infer_model(LANE_HEF)
        self.infer_model.input().set_format_type(FormatType.UINT8)
        for o in self.hef.get_output_vstream_infos():
            self.infer_model.output(o.name).set_format_type(FormatType.FLOAT32)
        self._output_shapes = {
            o.name: self.infer_model.output(o.name).shape
            for o in self.hef.get_output_vstream_infos()
        }
        self._ctx = self.infer_model.configure()
        self.configured = self._ctx.__enter__()

    def infer(self, model_input: np.ndarray) -> np.ndarray:
        """Run one frame through the model and return the concatenated
        (1, total_features) output tensor UFLDProcessing.get_coordinates()
        expects — same slice1..4 concatenation the original offline
        postprocess_output() did."""
        output_buffers = {
            name: np.empty(shape, dtype=np.float32)
            for name, shape in self._output_shapes.items()
        }
        bindings = self.configured.create_bindings(output_buffers=output_buffers)
        bindings.input().set_buffer(model_input)
        self.configured.wait_for_async_ready(timeout_ms=5000)
        job = self.configured.run_async([bindings])
        job.wait(5000)

        slices = [
            bindings.output(f"ufld_v2_tu/slice{i}").get_buffer().reshape(1, -1)
            for i in (1, 2, 3, 4)
        ]
        return np.concatenate(slices, axis=1)


def _lane_offset_px(lanes: list, frame_w: int) -> float | None:
    """Signed pixel offset of the estimated lane center from the frame's
    horizontal center: negative = lane center is left of us (steer left to
    recenter), positive = steer right. None if no lane is usable this
    frame.

    `lanes` is UFLDProcessing.get_coordinates()'s output: up to 4 point
    lists (row-based ego-lane boundaries first, then column-based outer
    lanes), each point list running from far (small y, top of frame) to
    near (large y, bottom of frame) since row_anchor/col_anchor ascend.
    We only care about each lane's nearest-to-robot point for steering.
    """
    near_x = []
    for lane in lanes:
        if not lane:
            continue
        near_x.append(max(lane, key=lambda p: p[1])[0])

    if not near_x:
        return None

    if len(near_x) == 1:
        # Only one lane boundary visible — assume a quarter-frame-wide lane
        # and steer to restore that assumed half-width, rather than doing
        # nothing until the other boundary reappears.
        assumed_half_lane = frame_w / 4
        x = near_x[0]
        estimated_center = x + assumed_half_lane if x < frame_w / 2 else x - assumed_half_lane
        return estimated_center - frame_w / 2

    lane_center = (min(near_x) + max(near_x)) / 2
    return lane_center - frame_w / 2


def _offset_to_command(offset: float | None) -> str:
    if offset is None:
        return "STOP"
    if abs(offset) <= CENTER_DEADBAND_PX:
        return "FORWARD"
    return "RIGHT" if offset > 0 else "LEFT"


def _run():
    logger.info("Lane-detect thread started")
    state.systemStatus = "LaneDetect: RUNNING"

    detector: _LaneDetector | None = None
    processor: UFLDProcessing | None = None
    last_seen = time.monotonic()

    while not _stop_event.is_set():
        try:
            frame_rgb = camera_threads.get_last_cam1_frame()
            if frame_rgb is None:
                time.sleep(LOOP_DELAY)
                continue

            # UFLDProcessing/the compiled HEF were built against the
            # original example's plain cv2.VideoCapture (BGR) frames —
            # camera_threads stores cam-1's feed as RGB for display, so
            # convert back before feeding the model.
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
            h, w = frame_bgr.shape[:2]

            if detector is None:
                detector = _LaneDetector()
            if processor is None:
                processor = UFLDProcessing(
                    num_cell_row=100, num_cell_col=100,
                    num_row=56, num_col=41, num_lanes=4,
                    crop_ratio=0.8,
                    original_frame_width=w, original_frame_height=h,
                    total_frames=0,
                )

            model_input = processor.resize(frame_bgr, MODEL_INPUT_H, MODEL_INPUT_W).astype(np.uint8)
            output_tensor = detector.infer(model_input)
            lanes = processor.get_coordinates(output_tensor)

            offset = _lane_offset_px(lanes, w)
            now = time.monotonic()
            if offset is not None:
                last_seen = now
                cmd = _offset_to_command(offset)
            elif now - last_seen <= LOST_LANE_TIMEOUT_S:
                cmd = "FORWARD"   # brief single-frame dropout — don't jerk to a stop
            else:
                cmd = "STOP"      # lane genuinely lost
            send_command("dev00", cmd)
            state.systemStatus = f"LaneDetect: {cmd} | offset={offset}"
        except Exception as e:
            logger.error("Lane-detect step error: %s", e)
            send_command("dev00", "STOP")
        time.sleep(LOOP_DELAY)

    send_command("dev00", "STOP")
    state.systemStatus = "LaneDetect: STOPPED"
    logger.info("Lane-detect thread stopped")


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_run, daemon=True, name="LaneDetect")
    _thread.start()
    print("🛣️  Lane-detect mode started")


def stop() -> None:
    _stop_event.set()
    if _thread:
        _thread.join(timeout=2.0)
    print("🛣️  Lane-detect mode stopped")
