# face_id.py — who's in front of her: recognising people by face
#
# Only when someone's there (cam-1's IMX500 sees a "person"), about once a
# second: the largest face in cam-1's frame (face_emotion_mode's Hailo
# detector) is turned into a 512-number fingerprint by ArcFace MobileFaceNet
# on the CPU (onnxruntime, ~30 ms on a Pi 5) and compared with the people
# she's been introduced to. Two matching looks in a row = recognised.
#
#   state.person_name   who's there now (None = nobody she knows / nobody)
#   Mind.on_person()    she greets them by name (or asks a stranger's name),
#                       and knows who she's talking to
#
# Introductions (voice_commands.py): "remember my face" (uses the name she
# already knows — "my name is Sam" first), "remember this face as Sam",
# "who am I", "who do you see", "forget my face".
#
# Privacy: only the fingerprints are stored (memories/faces.json, gitignored),
# never a picture, and "forget my face" / "forget everything" delete them.
#
# Model: resources/onnx/w600k_mbf.onnx — from InsightFace's buffalo_s pack.
# Get it once with:  python3 face_id.py --download
# Without it, face ID simply stays off.

import io
import json
import os
import sys
import threading
import time
import zipfile
from pathlib import Path

import numpy as np

import state

BASE_DIR     = Path(__file__).resolve().parent.parent
MODEL_PATH   = BASE_DIR / "resources" / "onnx" / "w600k_mbf.onnx"
MODEL_URL    = "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_s.zip"
FACES_PATH   = BASE_DIR / "memories" / "faces.json"

MATCH        = 0.40     # cosine similarity that counts as the same person (unaligned crops, so modest)
CONFIRM      = 2        # consecutive matching looks before she's sure
LOOK_S       = 1.0      # how often she looks while someone's there and unrecognised
RECHECK_S    = 10.0     # ...and once she knows who it is
ENROLL_SHOTS = 8
ENROLL_S     = 12.0
KEEP_PER_PERSON = 24
STRANGER_LOOKS = 4      # unmatched looks in a row before "someone I don't know"

_lock = threading.Lock()
_faces: dict | None = None          # name -> {"embeddings": [[...512]], "created": ts}
_session = None
_input_name = None
_thread = None
_stop = threading.Event()
_enrolling = None                   # {"name", "shots": [], "until", "done": Event, "ok": bool}


# ── model ────────────────────────────────────────────────────────────────
def download_model() -> bool:
    import urllib.request
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    print(f"⬇️  Downloading {MODEL_URL} …")
    data = urllib.request.urlopen(MODEL_URL, timeout=120).read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        name = next((n for n in z.namelist() if n.endswith("w600k_mbf.onnx")), None)
        if not name:
            print("❌ w600k_mbf.onnx isn't in that archive")
            return False
        MODEL_PATH.write_bytes(z.read(name))
    print(f"✅ Saved {MODEL_PATH}")
    return True


def available() -> bool:
    return MODEL_PATH.is_file()


def _model():
    global _session, _input_name
    if _session is None:
        import onnxruntime as ort
        _session = ort.InferenceSession(str(MODEL_PATH), providers=["CPUExecutionProvider"])
        _input_name = _session.get_inputs()[0].name
    return _session


def embed(face_rgb: np.ndarray) -> np.ndarray:
    """A face crop (RGB) -> unit-length 512-d fingerprint."""
    import cv2
    x = cv2.resize(face_rgb, (112, 112)).astype(np.float32)
    x = ((x - 127.5) / 127.5).transpose(2, 0, 1)[None]
    v = _model().run(None, {_input_name: x})[0][0].astype(np.float32)
    return v / (np.linalg.norm(v) + 1e-9)


def _crop(frame: np.ndarray, box) -> np.ndarray | None:
    """Square crop around a face box with a little margin (ArcFace wants the whole face)."""
    x1, y1, x2, y2 = box
    h, w = frame.shape[:2]
    cx, cy, side = (x1 + x2) / 2, (y1 + y2) / 2, max(x2 - x1, y2 - y1) * 1.25
    a, b = int(max(0, cx - side / 2)), int(max(0, cy - side / 2))
    c, d = int(min(w, cx + side / 2)), int(min(h, cy + side / 2))
    if c - a < 24 or d - b < 24:
        return None               # too small / far to recognise
    return frame[b:d, a:c]


# ── the people she knows ─────────────────────────────────────────────────
def _load() -> dict:
    global _faces
    if _faces is None:
        try:
            _faces = json.loads(FACES_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _faces = {}
    return _faces


def _save() -> None:
    FACES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = FACES_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(_faces), encoding="utf-8")
    os.replace(tmp, FACES_PATH)


def people() -> list:
    with _lock:
        return sorted(_load())


def match(v: np.ndarray) -> tuple[str | None, float]:
    best, score = None, 0.0
    with _lock:
        for name, rec in _load().items():
            embs = np.asarray(rec["embeddings"], dtype=np.float32)
            if len(embs):
                s = float(np.max(embs @ v))
                if s > score:
                    best, score = name, s
    return (best, score) if score >= MATCH else (None, score)


def forget(name: str) -> bool:
    with _lock:
        faces = _load()
        key = next((k for k in faces if k.lower() == name.lower()), None)
        if key is None:
            return False
        del faces[key]
        _save()
    if state.person_name and state.person_name.lower() == name.lower():
        state.person_name = None
    return True


def forget_all() -> None:
    global _faces
    with _lock:
        _faces = {}
        _save()
    state.person_name = None


def enroll(name: str, timeout_s: float = ENROLL_S) -> bool:
    """Learn the face in front of her as `name` (blocking, up to timeout_s).
    Returns True once she has enough good looks."""
    global _enrolling
    if not available():
        return False
    job = {"name": name.strip().title(), "shots": [], "until": time.monotonic() + timeout_s,
           "done": threading.Event(), "ok": False}
    _enrolling = job
    job["done"].wait(timeout_s + 2)
    _enrolling = None
    return job["ok"]


def _finish_enroll(job) -> None:
    with _lock:
        faces = _load()
        rec = faces.setdefault(job["name"], {"embeddings": [], "created": time.time()})
        rec["embeddings"] = (rec["embeddings"] + [[round(float(x), 5) for x in v] for v in job["shots"]])[-KEEP_PER_PERSON:]
        _save()
    job["ok"] = True
    state.person_name, state.person_seen_ts = job["name"], time.time()
    print(f"🙂 Learned {job['name']}'s face ({len(job['shots'])} looks)")


# ── watching ─────────────────────────────────────────────────────────────
def _person_in_view() -> bool:
    return any(str(label).lower() == "person" for label, _ in (getattr(state, "cam1_detection_labels", None) or []))


def _tell_mind(name) -> None:
    try:
        import kida_mind_host
        if kida_mind_host.MIND is not None:
            kida_mind_host.MIND.on_person(name)
    except Exception as e:
        print(f"[face_id] mind: {e}")
    try:
        import daylog
        daylog.note_person(name)
    except Exception:
        pass


def _loop() -> None:
    import camera_threads
    import face_emotion_mode
    streak_name, streak = None, 0
    strangers = 0
    last_look = 0.0
    while not _stop.is_set():
        time.sleep(0.25)
        job = _enrolling
        now = time.monotonic()
        known_recently = state.person_name and time.time() - state.person_seen_ts < 30
        interval = 0.4 if job else (RECHECK_S if known_recently else LOOK_S)
        if now - last_look < interval:
            continue
        if not job and not _person_in_view():
            if state.person_name and time.time() - state.person_seen_ts > 60:
                state.person_name = None          # they've gone
            streak, strangers = 0, 0
            continue
        last_look = now
        try:
            frame = camera_threads.get_last_cam1_frame()
            if frame is None:
                continue
            boxes = face_emotion_mode.detect_faces(frame)
            if not boxes:
                continue
            crop = _crop(frame, max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1])))
            if crop is None:
                continue
            v = embed(crop)

            if job:                                   # being introduced
                job["shots"].append(v)
                if len(job["shots"]) >= ENROLL_SHOTS:
                    _finish_enroll(job)
                    job["done"].set()
                    _tell_mind(job["name"])
                elif now > job["until"]:
                    job["done"].set()
                continue

            name, score = match(v)
            if name:
                strangers = 0
                streak = streak + 1 if name == streak_name else 1
                streak_name = name
                if streak >= CONFIRM:
                    fresh = state.person_name != name or time.time() - state.person_seen_ts > 600
                    state.person_name, state.person_seen_ts = name, time.time()
                    if fresh:
                        print(f"🙂 That's {name} ({score:.2f})")
                        _tell_mind(name)
            else:
                streak_name, streak = None, 0
                strangers += 1
                if strangers == STRANGER_LOOKS and not state.person_name:
                    print(f"🤔 Someone I don't know (best {score:.2f})")
                    _tell_mind(None)
        except Exception as e:
            print(f"⚠️ face_id: {e}")
            time.sleep(2)


def start() -> None:
    global _thread
    if not available():
        print(f"🙂 Face ID off — no model at {MODEL_PATH} (run: python3 face_id.py --download)")
        return
    if _thread is None:
        _thread = threading.Thread(target=_loop, daemon=True, name="FaceID")
        _thread.start()
        print(f"🙂 Face ID on — knows {len(people())} people")


if __name__ == "__main__":
    if "--download" in sys.argv:
        sys.exit(0 if download_model() else 1)
    print(__doc__ if __doc__ else "usage: python3 face_id.py --download")
