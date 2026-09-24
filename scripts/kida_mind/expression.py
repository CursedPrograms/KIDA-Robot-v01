"""
expression.py - reading your face, if you let her.

OFF by default. When it's on, she looks at the cam-1 frames published into
frames.py about once a second while someone is around, and
estimates a few things: is there a face, is it smiling, are the eyes visible
(closed or looking away reads as tired), how close is it to the camera. Those
become small nudges to her mood and a line in her prompt ("they look tired").

What this is not:
  * Not facial-landmark or micro-expression analysis. It uses OpenCV's classic
    Haar detectors (face, eyes, smile), which is what's installed. They read
    smiles, presence and drowsiness reasonably and cannot read sadness or anger,
    so what she perceives is skewed toward the positive. MediaPipe landmarks would
    do better and could replace analyze().
  * Not a recording. Frames stay in memory for a moment; only a few numbers are kept.

She only ever looks while the switch is on, and you can turn it off by asking.
"""

import os
import time

from . import store

try:
    import cv2
except ImportError:
    cv2 = None

FILE = "expression.json"

SMILE_STREAK = 3          # consecutive frames of smiling before it counts
DROWSY_STREAK = 6         # ...of a face with no eyes visible
SMILE_COOLDOWN_S = 90
DROWSY_COOLDOWN_S = 300
EMA = 0.25
FRESH_S = 20


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


class ExpressionSensor:
    def __init__(self):
        d = store.read_json(FILE, {}) or {}
        self.enabled = bool(d.get("enabled", False))
        self.last = None            # the latest reading
        self.last_ts = 0.0
        self.valence = 0.0          # smoothed
        self.arousal = 0.3
        self._smile_run = 0
        self._drowsy_run = 0
        self._last_smile = 0.0
        self._last_drowsy = 0.0
        self._seen_face_ts = 0.0
        self.face_cascade = self.eye_cascade = self.smile_cascade = None
        if cv2 is not None:
            def load(name):
                c = cv2.CascadeClassifier(os.path.join(cv2.data.haarcascades, name))
                return None if c.empty() else c
            self.face_cascade = load("haarcascade_frontalface_default.xml")
            self.eye_cascade = load("haarcascade_eye.xml")
            self.smile_cascade = load("haarcascade_smile.xml")

    @property
    def available(self):
        return cv2 is not None and self.face_cascade is not None

    def set_enabled(self, flag):
        self.enabled = bool(flag)
        store.write_json(FILE, {"enabled": self.enabled, "changed": time.time()})
        if not self.enabled:
            self.last, self._smile_run, self._drowsy_run = None, 0, 0

    # ------------------------------------------------------------ analysis
    def analyze(self, frame):
        """One frame -> a reading, or None if there's no face. (Swap this out for
        a landmark model to do better.)"""
        if not self.available or frame is None:
            return None
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        scale = 320.0 / gray.shape[1]
        if scale < 1.0:
            gray = cv2.resize(gray, (320, int(gray.shape[0] * scale)), interpolation=cv2.INTER_AREA)
        gray = cv2.equalizeHist(gray)
        faces = self.face_cascade.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=5, minSize=(40, 40))
        if len(faces) == 0:
            return None
        x, y, w, h = max(faces, key=lambda r: r[2] * r[3])
        size = (w * h) / float(gray.shape[0] * gray.shape[1])

        eyes = 0
        if self.eye_cascade is not None:
            eyes = len(self.eye_cascade.detectMultiScale(gray[y:y + int(h * 0.6), x:x + w], scaleFactor=1.1, minNeighbors=6, minSize=(12, 12)))
        smile = False
        if self.smile_cascade is not None:
            lower = gray[y + h // 2:y + h, x:x + w]
            if lower.size:
                smile = len(self.smile_cascade.detectMultiScale(lower, scaleFactor=1.6, minNeighbors=22, minSize=(20, 10))) > 0

        valence = 0.6 if smile else -0.05
        arousal = _clamp(0.3 + (0.2 if size > 0.12 else 0.0) + (0.15 if smile else 0.0) - (0.25 if eyes == 0 else 0.0))
        return {"smile": smile, "eyes": eyes, "size": round(float(size), 3), "valence": valence, "arousal": arousal}

    def observe(self, frame, now=None):
        """Look at one frame. Returns an event ("smile", "drowsy", "arrived") the
        first time something notable happens, else None."""
        now = now or time.time()
        r = self.analyze(frame)
        if r is None:
            self._smile_run = self._drowsy_run = 0
            return None
        arrived = now - self._seen_face_ts > 30
        self._seen_face_ts = now
        self.last, self.last_ts = r, now
        self.valence += EMA * (r["valence"] - self.valence)
        self.arousal += EMA * (r["arousal"] - self.arousal)

        self._smile_run = self._smile_run + 1 if r["smile"] else 0
        self._drowsy_run = self._drowsy_run + 1 if r["eyes"] == 0 else 0
        if self._smile_run >= SMILE_STREAK and now - self._last_smile > SMILE_COOLDOWN_S:
            self._last_smile = now
            return "smile"
        if self._drowsy_run >= DROWSY_STREAK and now - self._last_drowsy > DROWSY_COOLDOWN_S:
            self._last_drowsy = now
            return "drowsy"
        if arrived:
            return "arrived"
        return None

    # ------------------------------------------------------------ reporting
    def describe(self, now=None):
        """Words for how they look right now, or "" (off, no face, or stale)."""
        now = now or time.time()
        if not self.enabled or self.last is None or now - self.last_ts > FRESH_S:
            return ""
        parts = []
        if self._smile_run >= 2:
            parts.append("smiling")
        if self._drowsy_run >= DROWSY_STREAK:
            parts.append("tired")
        return " and ".join(parts)

    def summary(self, now=None):
        now = now or time.time()
        return {"enabled": self.enabled, "available": self.available,
                "face_now": self.last is not None and now - self.last_ts < FRESH_S,
                "looks": self.describe(now)}
