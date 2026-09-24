"""
frames.py - the camera, shared.

Only one thing can hold a camera open at a time, and KIDA's cam-1 loop
(imx500_cam1.py, or camera_threads' plain cam-1 loop) already does. So
instead of opening a second capture that would fight it, that loop
*publishes* a frame here every half second, and the mind reads the latest
one. That also means the mind never turns a camera on by itself: no cam-1,
no frames.

Frames are kept in memory only (small, one at a time) and are never written to disk here.
"""

import threading
import time

try:
    import cv2
except ImportError:
    cv2 = None

MAX_WIDTH = 480

_lock = threading.Lock()
_frame = None
_ts = 0.0


def publish(frame):
    """Called by whatever owns the camera, with each frame it reads (BGR uint8)."""
    global _frame, _ts
    if frame is None:
        return
    if cv2 is not None and frame.shape[1] > MAX_WIDTH:
        scale = MAX_WIDTH / frame.shape[1]
        frame = cv2.resize(frame, (MAX_WIDTH, int(frame.shape[0] * scale)), interpolation=cv2.INTER_AREA)
    with _lock:
        _frame = frame.copy()
        _ts = time.time()


def latest(max_age_s=5.0):
    """(frame, timestamp) of the newest published frame, or (None, 0.0) if there
    isn't one fresher than `max_age_s`."""
    with _lock:
        if _frame is None or time.time() - _ts > max_age_s:
            return None, 0.0
        return _frame.copy(), _ts


def clear():
    global _frame, _ts
    with _lock:
        _frame, _ts = None, 0.0
