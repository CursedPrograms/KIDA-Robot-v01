# face_emotion_mode.py — event-driven face + emotion perception for KIDA
#
# Always-on background thread (not a drive mode — same idea as
# ambient_narration.py), but it only actually fires a capture when there's
# a reason to: the PIR motion sensor tripped, or the YOLO/IMX500 inference
# pipeline sees a "person" — instead of blindly polling on a timer. Keeps
# the Hailo-8L idle the rest of the time, so it stays a light, occasional
# guest rather than competing with kida_chat_wakeword.py's Whisper STT for
# throughput. Both share the device via HailoRT's multi_process_service
# scheduler (group_id="SHARED") — the same mechanism the old lane-detect
# mode used.
#
# Pipeline per triggered capture:
#   cam-1's always-on feed (camera_threads.get_last_cam1_frame())
#   -> face detection on the Hailo-8L (lightface_slim.hef — "Ultra-Light-
#      Fast-Generic-Face-Detector", 320x240 SSD-style, 4 feature-map scales)
#   -> crop the largest face -> emotion classification (ONNX FER+ model,
#      64x64 grayscale, runs on CPU — tiny enough not to need the NPU)
#   -> state.detected_emotion, read by hud_draw.py and
#      kida_chat_wakeword.py's _camera_context() (fed to the LLM)
#
# Decode constants below (feature maps, min_boxes, variances) match this
# exact compiled HEF — verified against a real captured photo before being
# wired in here: see the priors math, not guesswork.

import threading
import time

import cv2
import numpy as np
import onnxruntime as ort
from hailo_platform import HEF, VDevice, HailoSchedulingAlgorithm, FormatType

import camera_threads
import state
from pathlib import Path

BASE_DIR     = Path(__file__).resolve().parent.parent
FACE_HEF     = str(BASE_DIR / "resources" / "hefs" / "h8l" / "face_emotion" / "lightface_slim.hef")
EMOTION_ONNX = str(BASE_DIR / "resources" / "onnx" / "emotion-ferplus-8.onnx")

POLL_INTERVAL_S         = 0.5     # how often we cheaply check the trigger conditions
MIN_CAPTURE_INTERVAL_S  = 120.0   # cooldown between captures even under continuous motion/person presence

# ── lightface_slim decode config (320x240 input, 4 SSD-style scales) ──
FACE_INPUT_SIZE = (320, 240)   # (w, h)
FEATURE_MAPS    = [(40, 30), (20, 15), (10, 8), (5, 4)]   # (w, h) per scale
MIN_BOXES       = [[10, 16, 24], [32, 48], [64, 96], [128, 192, 256]]
CENTER_VARIANCE = 0.1
SIZE_VARIANCE   = 0.2
IOU_THRESHOLD   = 0.3
CONF_THRESHOLD  = 0.6

# Each scale's location/confidence outputs, keyed by that scale's (h, w)
_LOC_NAMES = {
    (30, 40): "lightface_slim/conv23", (15, 20): "lightface_slim/conv13",
    (8, 10):  "lightface_slim/conv18", (4, 5):   "lightface_slim/conv21",
}
_CLS_NAMES = {
    (30, 40): "lightface_slim/conv22", (15, 20): "lightface_slim/conv12",
    (8, 10):  "lightface_slim/conv17", (4, 5):   "lightface_slim/conv20",
}

EMOTION_LABELS = ["neutral", "happiness", "surprise", "sadness",
                  "anger", "disgust", "fear", "contempt"]

_thread: threading.Thread | None = None
_stop_event = threading.Event()


def _generate_priors() -> np.ndarray:
    priors = []
    for (fw, fh), min_boxes in zip(FEATURE_MAPS, MIN_BOXES):
        for j in range(fh):
            for i in range(fw):
                x_center = (i + 0.5) / fw
                y_center = (j + 0.5) / fh
                for min_box in min_boxes:
                    w = min_box / FACE_INPUT_SIZE[0]
                    h = min_box / FACE_INPUT_SIZE[1]
                    priors.append([x_center, y_center, w, h])
    priors = np.array(priors, dtype=np.float32)
    np.clip(priors, 0.0, 1.0, out=priors)
    return priors


_PRIORS = _generate_priors()


def _decode_boxes(locations: np.ndarray) -> np.ndarray:
    centers = np.concatenate([
        locations[..., :2] * CENTER_VARIANCE * _PRIORS[..., 2:] + _PRIORS[..., :2],
        np.exp(locations[..., 2:] * SIZE_VARIANCE) * _PRIORS[..., 2:],
    ], axis=-1)
    return np.concatenate([
        centers[..., :2] - centers[..., 2:] / 2,
        centers[..., :2] + centers[..., 2:] / 2,
    ], axis=-1)


def _softmax(x: np.ndarray, axis: int = -1) -> np.ndarray:
    e = np.exp(x - np.max(x, axis=axis, keepdims=True))
    return e / np.sum(e, axis=axis, keepdims=True)


def _iou(box: np.ndarray, boxes: np.ndarray) -> np.ndarray:
    x1 = np.maximum(box[0], boxes[:, 0]); y1 = np.maximum(box[1], boxes[:, 1])
    x2 = np.minimum(box[2], boxes[:, 2]); y2 = np.minimum(box[3], boxes[:, 3])
    inter   = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
    area_a  = (box[2] - box[0]) * (box[3] - box[1])
    area_b  = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    return inter / (area_a + area_b - inter + 1e-9)


def _nms(boxes: np.ndarray, scores: np.ndarray) -> list:
    idxs = scores.argsort()[::-1]
    picked = []
    while len(idxs):
        cur = idxs[0]
        picked.append(cur)
        if len(idxs) == 1:
            break
        rest = idxs[1:]
        idxs = rest[_iou(boxes[cur], boxes[rest]) <= IOU_THRESHOLD]
    return picked


class _FaceDetector:
    """Owns one shared-group VDevice for lightface_slim — lazily created so
    importing this module doesn't touch the Hailo-8L until the ambient
    thread actually ticks."""

    def __init__(self):
        self.hef = HEF(FACE_HEF)
        params = VDevice.create_params()
        params.scheduling_algorithm = HailoSchedulingAlgorithm.ROUND_ROBIN
        params.multi_process_service = True
        params.group_id = "SHARED"
        self.target = VDevice(params)
        self.infer_model = self.target.create_infer_model(FACE_HEF)
        self.infer_model.input().set_format_type(FormatType.UINT8)
        for o in self.hef.get_output_vstream_infos():
            self.infer_model.output(o.name).set_format_type(FormatType.FLOAT32)
        self._output_shapes = {
            o.name: self.infer_model.output(o.name).shape
            for o in self.hef.get_output_vstream_infos()
        }
        self._ctx = self.infer_model.configure()
        self.configured = self._ctx.__enter__()

    def detect(self, frame_rgb: np.ndarray) -> list:
        """Return [(x1, y1, x2, y2), ...] face boxes in frame_rgb's own pixel coords."""
        h, w = frame_rgb.shape[:2]
        resized = cv2.resize(frame_rgb, FACE_INPUT_SIZE).astype(np.uint8)

        output_buffers = {
            name: np.empty(shape, dtype=np.float32)
            for name, shape in self._output_shapes.items()
        }
        bindings = self.configured.create_bindings(output_buffers=output_buffers)
        bindings.input().set_buffer(resized)
        self.configured.wait_for_async_ready(timeout_ms=5000)
        job = self.configured.run_async([bindings])
        job.wait(5000)
        outputs = {name: bindings.output(name).get_buffer() for name in self._output_shapes}

        all_boxes, all_scores = [], []
        for (fw, fh) in FEATURE_MAPS:
            key = (fh, fw)
            loc = outputs[_LOC_NAMES[key]].astype(np.float32)
            cls = outputs[_CLS_NAMES[key]].astype(np.float32)
            n_anchors = loc.shape[-1] // 4
            all_boxes.append(loc.reshape(fh, fw, n_anchors, 4).reshape(-1, 4))
            all_scores.append(cls.reshape(fh, fw, n_anchors, 2).reshape(-1, 2))

        locations = np.concatenate(all_boxes, axis=0)
        scores    = np.concatenate(all_scores, axis=0)
        boxes     = _decode_boxes(locations)
        face_scores = _softmax(scores, axis=-1)[:, 1]

        mask = face_scores > CONF_THRESHOLD
        if not mask.any():
            return []
        cand_boxes  = boxes[mask]
        cand_scores = face_scores[mask]
        picked = _nms(cand_boxes, cand_scores)

        result = []
        for p in picked:
            b = cand_boxes[p]
            x1, y1 = max(0, int(b[0] * w)), max(0, int(b[1] * h))
            x2, y2 = min(w, int(b[2] * w)), min(h, int(b[3] * h))
            if x2 > x1 and y2 > y1:
                result.append((x1, y1, x2, y2))
        return result


class _EmotionClassifier:
    """Tiny 64x64-grayscale ONNX model — cheap enough to run on the Pi's CPU
    per detected face, no need to spend NPU budget on it."""

    def __init__(self):
        self.session    = ort.InferenceSession(EMOTION_ONNX, providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name

    def classify(self, face_rgb: np.ndarray) -> tuple[str, float]:
        gray     = cv2.cvtColor(face_rgb, cv2.COLOR_RGB2GRAY)
        resized  = cv2.resize(gray, (64, 64)).astype(np.float32).reshape(1, 1, 64, 64)
        logits   = self.session.run(None, {self.input_name: resized})[0][0]
        probs    = _softmax(logits)
        idx      = int(np.argmax(probs))
        return EMOTION_LABELS[idx], float(probs[idx])


_detector: "_FaceDetector | None" = None
_detector_lock = threading.Lock()


def detect_faces(frame_rgb: np.ndarray) -> list:
    """Face boxes in frame_rgb — the one shared Hailo detector, also used by
    face_id.py (recognising who's there), so there's a single VDevice for it."""
    global _detector
    with _detector_lock:
        if _detector is None:
            _detector = _FaceDetector()
        return _detector.detect(frame_rgb)


def _motion_active() -> bool:
    return str(getattr(state, "motionValue", "0")) in ("1", "HIGH", "True")


def _person_in_view() -> bool:
    """True if either cam-0's YOLO or cam-1's on-chip IMX500 detector
    currently sees a person."""
    cam0_labels = getattr(state, "detection_labels", None) or []
    cam1_labels = getattr(state, "cam1_detection_labels", None) or []
    return any(name.lower() == "person" for name, _ in cam0_labels) \
        or any(name.lower() == "person" for name, _ in cam1_labels)


def _should_capture() -> bool:
    return _motion_active() or _person_in_view()


def _loop() -> None:
    emotion_clf: _EmotionClassifier | None = None
    last_capture = 0.0

    while not _stop_event.is_set():
        if _stop_event.wait(POLL_INTERVAL_S):
            break
        try:
            if not _should_capture():
                continue

            now = time.monotonic()
            if now - last_capture < MIN_CAPTURE_INTERVAL_S:
                continue
            last_capture = now

            frame = camera_threads.get_last_cam1_frame()
            if frame is None:
                continue

            if emotion_clf is None:
                emotion_clf = _EmotionClassifier()

            boxes = detect_faces(frame)
            if not boxes:
                state.detected_emotion = None
                continue

            x1, y1, x2, y2 = max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
            label, conf = emotion_clf.classify(frame[y1:y2, x1:x2])
            state.detected_emotion = (label, conf)
        except Exception as e:
            print(f"⚠️ face_emotion_mode error: {e}")


def start() -> None:
    """Start the ambient background thread. Safe to call once at boot."""
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_loop, daemon=True)
    _thread.start()
    print("😊 Face-emotion ambient thread started")


def stop() -> None:
    _stop_event.set()
