# imx500_cam1.py — IMX500 on-chip object detection for KIDA cam-1
# Runs inference on the camera SoC (no Pi CPU cost), draws boxes via OpenCV,
# and pushes annotated RGB frames into frame_queue2 for ui.py to display.

import threading
import time
import cv2

from picamera2 import Picamera2
from picamera2.devices import IMX500
from picamera2.devices.imx500 import NetworkIntrinsics, postprocess_nanodet_detection

from camera_threads import frame_queue2, drop_put

MODEL_PATH  = "/usr/share/imx500-models/imx500_network_ssd_mobilenetv2_fpnlite_320x320_pp.rpk"
LABELS_PATH = "assets/coco_labels.txt"
THRESHOLD   = 0.55
IOU         = 0.65
MAX_DETS    = 10

_stop_event  = threading.Event()
_imx500      = None
_picam2_ai   = None
_intrinsics  = None
_labels: list = []


def _load_labels() -> list:
    try:
        with open(LABELS_PATH) as f:
            return f.read().splitlines()
    except FileNotFoundError:
        return [str(i) for i in range(80)]


def _parse_detections(metadata) -> list:
    np_outputs = _imx500.get_outputs(metadata, add_batch=True)
    if np_outputs is None:
        return []
    input_w, input_h = _imx500.get_input_size()
    if _intrinsics.postprocess == "nanodet":
        boxes, scores, classes = postprocess_nanodet_detection(
            outputs=np_outputs[0], conf=THRESHOLD,
            iou_thres=IOU, max_out_dets=MAX_DETS,
        )[0]
        from picamera2.devices.imx500.postprocess import scale_boxes
        boxes = scale_boxes(boxes, 1, 1, input_h, input_w, False, False)
    else:
        boxes, scores, classes = np_outputs[0][0], np_outputs[1][0], np_outputs[2][0]
        if _intrinsics.bbox_normalization:
            boxes = boxes / input_h
        if _intrinsics.bbox_order == "xy":
            boxes = boxes[:, [1, 0, 3, 2]]
    return [
        (_imx500.convert_inference_coords(box, metadata, _picam2_ai), int(cat), float(score))
        for box, score, cat in zip(boxes, scores, classes)
        if score > THRESHOLD
    ]


def _draw_detections(frame, detections: list):
    for (x, y, w, h), cat, score in detections:
        label = f"{_labels[cat] if cat < len(_labels) else cat} ({score:.2f})"
        (tw, th), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        tx, ty = x + 5, y + 15
        overlay = frame.copy()
        cv2.rectangle(overlay, (tx, ty - th), (tx + tw, ty + baseline),
                      (255, 255, 255), cv2.FILLED)
        cv2.addWeighted(overlay, 0.30, frame, 0.70, 0, frame)
        cv2.putText(frame, label, (tx, ty),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
    return frame


def _imx500_loop() -> None:
    last_detections: list = []
    while not _stop_event.is_set():
        try:
            request = _picam2_ai.capture_request()
            try:
                metadata = request.get_metadata()
                frame = request.make_array("main").copy()
            finally:
                request.release()
            detections = _parse_detections(metadata)
            if detections:
                last_detections = detections
            frame = _draw_detections(frame, last_detections)
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame = cv2.flip(frame, 1)
            drop_put(frame_queue2, frame)
        except Exception as e:
            print(f"[IMX500 Cam1] {e}")
            time.sleep(0.05)


def create_imx500_camera(model_path: str = MODEL_PATH) -> Picamera2:
    """Initialise IMX500 + Picamera2 for cam-1. Returns the Picamera2 instance."""
    global _imx500, _picam2_ai, _intrinsics, _labels

    _imx500 = IMX500(model_path)
    _intrinsics = _imx500.network_intrinsics
    if not _intrinsics:
        _intrinsics = NetworkIntrinsics()
        _intrinsics.task = "object detection"

    if _intrinsics.labels is None:
        _labels = _load_labels()
        _intrinsics.labels = _labels
    else:
        _labels = list(_intrinsics.labels)

    _intrinsics.update_with_defaults()

    _picam2_ai = Picamera2(_imx500.camera_num)
    cfg = _picam2_ai.create_preview_configuration(
        controls={"FrameRate": _intrinsics.inference_rate},
        buffer_count=12,
    )
    _imx500.show_network_fw_progress_bar()
    _picam2_ai.start(cfg)

    if _intrinsics.preserve_aspect_ratio:
        _imx500.set_auto_aspect_ratio()

    print("✅ IMX500 Cam-1 ready")
    return _picam2_ai


def start_imx500_cam1() -> None:
    """Start the background inference thread."""
    _stop_event.clear()
    threading.Thread(target=_imx500_loop, daemon=True).start()
    print("✅ IMX500 Cam-1 inference thread started")


def stop_imx500_cam1() -> None:
    """Signal the inference thread to stop."""
    _stop_event.set()
