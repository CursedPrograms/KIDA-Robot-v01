# camera_threads.py — camera capture threads for KIDA
#
# Two cameras:
#   Cam-0  (frame_queue)   optional YOLO inference, started/stopped on demand
#   Cam-1  (frame_queue2)  always-on secondary feed

import os
import threading
import time
import cv2
from queue import Queue, Empty
import state

# Cam-0 YOLO runs on the Pi's CPU (cam-1's IMX500 inference is on-chip and
# doesn't compete for CPU).  Left unchecked, a 640px predict() call takes
# ~0.25s and — running back-to-back in a tight loop — starves every other
# thread on a 4-core Pi (Arduino/MPU polling, Flask, wakeword), which looks
# like the whole app freezing the moment inference is toggled on.  Shrinking
# the inference resolution cuts that to ~0.08s, and capping torch's thread
# pool leaves the other threads a core to run on.
INFERENCE_IMGSZ = 320

try:
    import torch
    torch.set_num_threads(max(1, (os.cpu_count() or 4) // 2))
except ImportError:
    pass

# Each camera feeds two independent single-slot queues so the local pygame
# HUD (ui.py) and the Flask web dashboard (server.py) never fight over the
# same frame. They used to share one queue each; ui.py's tight non-blocking
# poll loop nearly always won the race for cam-0's slow (YOLO-throttled)
# frames, starving the web stream, which just kept re-serving its last
# cached frame — looking frozen on "the first frame".
frame_queue      = Queue(maxsize=1)   # cam-0, local pygame HUD
frame_queue_web  = Queue(maxsize=1)   # cam-0, web dashboard
frame_queue2     = Queue(maxsize=1)   # cam-1, local pygame HUD
frame_queue2_web = Queue(maxsize=1)   # cam-1, web dashboard
cam0_stop_event = threading.Event()

last_annotated_frame = None   # cam-0's most recent inference-drawn frame
last_cam1_frame      = None   # cam-1's most recent frame (RGB, mirrored)


def drop_put(queue: Queue, item) -> None:
    """Non-blocking put — drops the oldest frame if the queue is full."""
    if not queue.empty():
        try:
            queue.get_nowait()
        except Empty:
            pass
    queue.put(item)


_MIND_FRAME_EVERY_S = 0.5
_last_mind_frame = 0.0


def publish_to_mind(frame_bgr) -> None:
    """Hand cam-1's view to KIDA's inner life (kida_mind/frames.py) twice a
    second — her glances and (if you ask her to) expression reading use it,
    without ever opening a second camera handle."""
    global _last_mind_frame
    now = time.monotonic()
    if now - _last_mind_frame < _MIND_FRAME_EVERY_S:
        return
    _last_mind_frame = now
    try:
        from kida_mind import frames
        frames.publish(frame_bgr)
    except Exception:
        pass


def publish(frame, *queues: Queue) -> None:
    """Non-blocking publish of the same frame to one or more single-slot queues."""
    for q in queues:
        drop_put(q, frame)


def _camera_loop(picam2, model, task: str, queue: Queue,
                 stop_event: threading.Event) -> None:
    """Cam-0: optional YOLO inference.  Exits when stop_event is set."""
    global last_annotated_frame
    while not stop_event.is_set():
        try:
            frame = picam2.capture_array()
            if frame is None:
                continue
            # Mirror before inference so any box/label text r.plot() draws
            # comes out readable — mirroring after plot() flips the text too.
            frame = cv2.flip(frame, 1)
            if model and task == "detect":
                results = model.predict(
                    frame, conf=0.5, imgsz=INFERENCE_IMGSZ, verbose=False
                )
                r = results[0]
                # Publish labels so watchdog and LLM can read them
                if r.boxes is not None and len(r.boxes):
                    state.detection_labels = [
                        (r.names[int(cls)], float(conf))
                        for cls, conf in zip(r.boxes.cls, r.boxes.conf)
                    ]
                    # xyxyn = normalized (0-1) box coords, resolution-independent
                    # so watchdog's zone check doesn't care about frame size.
                    state.detection_boxes = [
                        {
                            "label": r.names[int(cls)],
                            "conf": float(conf),
                            "box": tuple(float(v) for v in box),
                        }
                        for cls, conf, box in zip(r.boxes.cls, r.boxes.conf, r.boxes.xyxyn)
                    ]
                else:
                    state.detection_labels = []
                    state.detection_boxes = []
                state.detection_boxes_ts = time.monotonic()
                out = r.plot()
            else:
                out = frame
            out = cv2.cvtColor(out, cv2.COLOR_BGR2RGB)
            if model and task == "detect":
                last_annotated_frame = out
            publish(out, queue, frame_queue_web)
        except Exception as e:
            print(f"[Cam0] {e}")
            time.sleep(0.05)


def get_last_inference_frame():
    """Return the most recent annotated (RGB, mirrored) cam-0 frame, or None."""
    return last_annotated_frame


def _camera2_loop(picam2_ai, queue: Queue) -> None:
    """Cam-1: always-on feed, no inference."""
    global last_cam1_frame
    while True:
        try:
            frame = picam2_ai.capture_array()
            if frame is None:
                continue
            publish_to_mind(frame)
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame = cv2.flip(frame, 1)
            last_cam1_frame = frame
            publish(frame, queue, frame_queue2_web)
        except Exception as e:
            print(f"[Cam1] {e}")
            time.sleep(0.05)


def get_last_cam1_frame():
    """Return the most recent cam-1 frame (RGB, mirrored), or None."""
    return last_cam1_frame


def start_cam1(picam2_ai) -> None:
    """Start the always-on cam-1 thread."""
    threading.Thread(
        target=_camera2_loop, args=(picam2_ai, frame_queue2), daemon=True
    ).start()
    print("✅ Cam-1 thread started")


def start_cam0(picam2, model, task: str) -> threading.Thread:
    """Start (or restart) the cam-0 inference thread."""
    cam0_stop_event.clear()
    t = threading.Thread(
        target=_camera_loop,
        args=(picam2, model, task, frame_queue, cam0_stop_event),
        daemon=True,
    )
    t.start()
    print("✅ Inference ON")
    return t


def stop_cam0() -> None:
    """Signal cam-0 to stop and drain its queues."""
    global last_annotated_frame
    cam0_stop_event.set()
    for q in (frame_queue, frame_queue_web):
        while not q.empty():
            try:
                q.get_nowait()
            except Empty:
                break
    last_annotated_frame = None
    print("🛑 Inference OFF")
