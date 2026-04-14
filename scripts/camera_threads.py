# camera_threads.py — camera capture threads for KIDA
#
# Two cameras:
#   Cam-0  (frame_queue)   optional YOLO inference, started/stopped on demand
#   Cam-1  (frame_queue2)  always-on secondary feed

import threading
import time
import cv2
from queue import Queue, Empty

frame_queue     = Queue(maxsize=1)   # cam-0
frame_queue2    = Queue(maxsize=1)   # cam-1
cam0_stop_event = threading.Event()


def _drop_put(queue: Queue, item) -> None:
    """Non-blocking put — drops the oldest frame if the queue is full."""
    if not queue.empty():
        try:
            queue.get_nowait()
        except Empty:
            pass
    queue.put(item)


def _camera_loop(picam2, model, task: str, queue: Queue,
                 stop_event: threading.Event) -> None:
    """Cam-0: optional YOLO inference.  Exits when stop_event is set."""
    while not stop_event.is_set():
        try:
            frame = picam2.capture_array()
            if frame is None:
                continue
            if model and task == "detect":
                results = model.predict(frame, conf=0.5, verbose=False)
                out = results[0].plot()
            else:
                out = frame
            out = cv2.cvtColor(out, cv2.COLOR_BGR2RGB)
            out = cv2.flip(out, 1)
            _drop_put(queue, out)
        except Exception as e:
            print(f"[Cam0] {e}")
            time.sleep(0.05)


def _camera2_loop(picam2_ai, queue: Queue) -> None:
    """Cam-1: always-on feed, no inference."""
    while True:
        try:
            frame = picam2_ai.capture_array()
            if frame is None:
                continue
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame = cv2.flip(frame, 1)
            _drop_put(queue, frame)
        except Exception as e:
            print(f"[Cam1] {e}")
            time.sleep(0.05)


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
    """Signal cam-0 to stop and drain its queue."""
    cam0_stop_event.set()
    while not frame_queue.empty():
        try:
            frame_queue.get_nowait()
        except Empty:
            break
    print("🛑 Inference OFF")
