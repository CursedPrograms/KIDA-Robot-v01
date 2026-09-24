"""
vision.py - perception of the room (KIDA's version of DREAM's vision.py).

DREAM sat still and looked at the photos its surveillance script saved. KIDA
drives around, so she looks differently:

  glances   about once a minute (while awake) the mind takes the newest cam-1
            frame (frames.py - published by her camera loop, never a second
            camera handle) and compares it with what she saw last. Who's there
            comes from the IMX500's on-chip person detections, which are far
            better than a Haar cascade, rather than from the image itself.
  photos    pictures you take with her (camera_actions.take_photo, config.IMAGE_DIR)
            are looked at too - you showed her something.
  motion    the PIR sensor, reported by kida_mind_host.py, is an observation
            with no picture.

Because she moves, "the room looks different" only means something if she
hasn't been driven since her last glance. After a drive the first glance is
simply "somewhere new", and it resets what she compares against.

No picture is ever written to disk: an observation is a few numbers and a
sentence ("the light changed, it got darker"), kept in memories/mind/.
"""

import os
import time
from pathlib import Path

import numpy as np

from . import store

try:
    import cv2
except ImportError:  # no OpenCV: no eyes, but everything else still works
    cv2 = None

OBSERVATIONS = "visual.jsonl"
STATE = "vision_state.json"
EYES = "eyes"            # where older versions kept thumbnails; forget() still clears it
THUMB = (16, 9)
MAX_PER_SCAN = 6
CORE_SIGNIFICANCE = 0.75


def _photo_dir():
    try:
        import config
        return Path(config.IMAGE_DIR).resolve()
    except Exception:
        return None


PHOTO_DIRS = None   # None = config.IMAGE_DIR; the self-test sets fake ones


def set_photo_dirs(dirs):
    """dirs: [(kind, path)] - the self-test uses fake ones."""
    global PHOTO_DIRS
    PHOTO_DIRS = [(k, Path(p)) for k, p in dirs]


def _dirs():
    if PHOTO_DIRS is not None:
        return PHOTO_DIRS
    d = _photo_dir()
    return [("photo", d)] if d else []


def _load_smile_detectors():
    if cv2 is None:
        return None, None
    face = cv2.CascadeClassifier(os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml"))
    smile = cv2.CascadeClassifier(os.path.join(cv2.data.haarcascades, "haarcascade_smile.xml"))
    return (face if not face.empty() else None), (smile if not smile.empty() else None)


class Vision:
    def __init__(self):
        self.available = cv2 is not None
        self.face_cascade, self.smile_cascade = _load_smile_detectors()
        s = store.read_json(STATE, {}) or {}
        self.last_mtime = s.get("last_mtime", 0.0)
        self.normal = np.array(s["normal"], dtype=np.float32) if s.get("normal") else None   # running mean thumbnail
        self.normal_n = s.get("normal_n", 0)
        self.last_thumb = np.array(s["last_thumb"], dtype=np.float32) if s.get("last_thumb") else None
        self.last_brightness = s.get("last_brightness")

    def _save(self):
        store.write_json(STATE, {
            "last_mtime": self.last_mtime, "normal_n": self.normal_n,
            "normal": self.normal.round(2).tolist() if self.normal is not None else None,
            "last_thumb": self.last_thumb.round(2).tolist() if self.last_thumb is not None else None,
            "last_brightness": self.last_brightness,
        })

    # ------------------------------------------------------------ looking
    def glance(self, frame_bgr, people=0, moved=False, now=None):
        """Look at one live frame. people: how many persons the IMX500 sees
        right now; moved: she's been driven since the last glance."""
        if not self.available or frame_bgr is None:
            return None
        now = now or time.time()
        if moved:   # a new place: what she compares against starts over here
            self.last_thumb, self.last_brightness = None, None
            self.normal, self.normal_n = None, 0
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        obs = self._observe_gray(gray, "look", now, people=people, moved=moved)
        store.append_jsonl(OBSERVATIONS, obs)
        self._save()
        return obs

    def scan(self, now=None):
        """Look at any photos taken since last time. Returns the new observations."""
        if not self.available:
            return []
        now = now or time.time()
        found = []
        for kind, folder in _dirs():
            if not folder.is_dir():
                continue
            for f in folder.iterdir():
                if f.suffix.lower() == ".jpg":
                    try:
                        mtime = f.stat().st_mtime
                    except OSError:
                        continue
                    if mtime > self.last_mtime:
                        found.append((mtime, kind, f))
        found.sort()
        observations = []
        for mtime, kind, f in found[:MAX_PER_SCAN]:
            img = cv2.imread(str(f), cv2.IMREAD_REDUCED_GRAYSCALE_2)
            if img is not None:
                obs = self._observe_gray(img, kind, mtime, detect_faces=True)
                obs["path"] = str(f)
                obs["text"] = "you showed me something: " + obs["text"] if obs["text"] != "nothing unusual" else "you took a photo with me"
                obs["significance"] = max(obs["significance"], 0.5)   # you chose to show her
                observations.append(obs)
                store.append_jsonl(OBSERVATIONS, obs)
            self.last_mtime = max(self.last_mtime, mtime)
        if len(found) > MAX_PER_SCAN:   # a backlog (she was off): skip ahead rather than grind through it
            self.last_mtime = found[-1][0]
        if found:
            self._save()
        return observations

    def record(self, text, kind="patrol", significance=0.7, now=None):
        """Something she noticed some other way (a route replay, say)."""
        now = now or time.time()
        obs = {"ts": now, "path": None, "kind": kind, "brightness": None, "delta": 0.0, "anomaly": 0.0,
               "faces": 0, "smiling": False, "significance": significance, "text": text,
               "core": significance >= CORE_SIGNIFICANCE, "spoken": False}
        store.append_jsonl(OBSERVATIONS, obs)
        return obs

    def record_motion(self, now=None):
        """The PIR sensor fired and nobody's in view."""
        now = now or time.time()
        obs = {"ts": now, "path": None, "kind": "motion", "brightness": None, "delta": 0.0, "anomaly": 0.0,
               "faces": 0, "smiling": False, "significance": 0.65, "text": "something moved near me",
               "core": False, "spoken": False}
        store.append_jsonl(OBSERVATIONS, obs)
        return obs

    def _observe_gray(self, img, kind, ts, people=0, moved=False, detect_faces=False):
        thumb = cv2.resize(img, THUMB, interpolation=cv2.INTER_AREA).astype(np.float32)
        brightness = float(thumb.mean())

        delta = float(np.abs(thumb - self.last_thumb).mean()) if self.last_thumb is not None else 0.0
        anomaly = float(np.abs(thumb - self.normal).mean()) if self.normal is not None and self.normal_n >= 5 else 0.0
        d_bright = (brightness - self.last_brightness) if self.last_brightness is not None else 0.0

        faces, smiling = people, False
        if self.face_cascade is not None and (detect_faces or people):
            found = self.face_cascade.detectMultiScale(img, scaleFactor=1.2, minNeighbors=5, minSize=(30, 30))
            faces = max(faces, len(found))
            if len(found) and self.smile_cascade is not None:   # a rough read of the expression
                x, y, w, h = max(found, key=lambda r: r[2] * r[3])
                lower = img[y + h // 2:y + h, x:x + w]
                if lower.size:
                    smiling = len(self.smile_cascade.detectMultiScale(lower, scaleFactor=1.7, minNeighbors=20)) > 0

        # what she now considers normal (here) absorbs this, slowly
        self.normal = thumb.copy() if self.normal is None else 0.9 * self.normal + 0.1 * thumb
        self.normal_n += 1
        self.last_thumb, self.last_brightness = thumb, brightness

        significance = max(0.7 * min(1.0, delta / 35.0), 0.85 * min(1.0, anomaly / 30.0),
                           0.6 if faces else 0.0, 0.3 if moved else 0.0)
        if faces:
            text = ("someone was in front of me" if faces == 1 else f"{faces} people were around me") + \
                   (" and looked like they were smiling" if smiling else "")
        elif moved:
            text = "I was somewhere new"
        elif abs(d_bright) > 25:
            text = "the light changed, it got " + ("brighter" if d_bright > 0 else "darker")
        elif anomaly > 20:
            text = "it looked different from how it usually does here"
        elif delta > 20:
            text = "something in front of me had changed"
        else:
            text = "nothing unusual"
        return {"ts": ts, "path": None, "kind": kind, "brightness": round(brightness, 1),
                "delta": round(delta, 1), "anomaly": round(anomaly, 1), "faces": faces, "smiling": smiling,
                "significance": round(significance, 2), "text": text,
                "core": significance >= CORE_SIGNIFICANCE, "spoken": False}

    # ------------------------------------------------------------ remembering
    def observations(self, limit=50):
        return store.read_jsonl(OBSERVATIONS)[-limit:]

    def unspoken_notable(self, min_significance=0.6, max_age_h=6, now=None):
        """The most striking thing she saw recently and hasn't mentioned."""
        now = now or time.time()
        # "someone was in front of me" isn't news to the person standing there
        cands = [o for o in self.observations(40)
                 if not o.get("spoken") and o["significance"] >= min_significance and now - o["ts"] < max_age_h * 3600
                 and not (o["kind"] == "look" and o["faces"])]
        return max(cands, key=lambda o: o["significance"]) if cands else None

    def mark_spoken(self, obs):
        items = store.read_jsonl(OBSERVATIONS)
        for o in items:
            if o["ts"] == obs["ts"] and o.get("path") == obs.get("path"):
                o["spoken"] = True
        store.write_jsonl(OBSERVATIONS, items)

    def latest_summary(self, now=None):
        now = now or time.time()
        obs = self.observations(1)
        if not obs:
            return ""
        o = obs[-1]
        ago = int((now - o["ts"]) / 60)
        when = "just now" if ago < 2 else f"{ago} minutes ago" if ago < 90 else f"{ago // 60} hours ago"
        return f"You last looked around {when}: {o['text']}."

    def presence_pattern(self):
        """When she usually sees someone: the hours with the most people, or []."""
        hours = {}
        for o in store.read_jsonl(OBSERVATIONS):
            if o.get("faces"):
                h = time.localtime(o["ts"]).tm_hour
                hours[h] = hours.get(h, 0) + 1
        return [h for h, c in sorted(hours.items(), key=lambda kv: -kv[1])[:3] if c >= 2]

    def forget(self):
        """Wipe what she saw, thumbnails included."""
        store.remove(OBSERVATIONS)
        store.remove(STATE)
        d = store.mind_dir() / EYES
        if d.is_dir():
            for f in d.glob("*.jpg"):
                f.unlink(missing_ok=True)
