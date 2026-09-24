# routes.py — record a drive, then replay it or patrol it
#
#   record   drive her around yourself; every ROUTE_STEP_CM (or a big turn) a
#            waypoint is kept, relative to where recording started, along
#            with a note of what she saw there: a 16x9 grey thumbnail, the
#            brightness, how many people cam-1 saw, and the nearest range.
#   replay   start her where you started recording, facing the same way,
#            and she drives the waypoints herself (navigator.py).
#   patrol   out along the route, back to the start, again, until stopped.
#
# On replay/patrol she looks again at each waypoint and compares with what
# the route remembers: much darker/brighter, the view changed, someone's
# there who wasn't (or the reverse), something in the way that wasn't. Any
# difference is handed to her inner life (Mind.notice), which may mention
# it — "something's different near the third stop: there's something in
# the way now."
#
# Routes live in memories/routes/<name>.json (gitignored, like the rest of
# what she remembers).

import json
import math
import os
import re
import threading
import time
from pathlib import Path

import state

ROUTES_DIR       = Path(__file__).resolve().parent.parent / "memories" / "routes"
ROUTE_STEP_CM    = 40.0
ROUTE_TURN_DEG   = 45.0
SAMPLE_S         = 0.3
DIFF_VIEW        = 35.0     # mean grey-level change (0-255) that counts as "looks different"
DIFF_BRIGHT      = 40.0
DIFF_RANGE_CM    = 40.0
MAX_NOTICES      = 2        # per run: one lasting change shouldn't become five remarks

_lock = threading.Lock()
_recording = None            # {"name", "origin", "waypoints"}
_rec_thread = None
_patrolling = threading.Event()
_current = {"name": None, "kind": None, "lap": 0, "differences": []}


def _safe(name: str) -> str:
    return re.sub(r"[^\w\- ]", "", (name or "").strip())[:40].strip() or "route"


def _path(name: str) -> Path:
    return ROUTES_DIR / f"{_safe(name).replace(' ', '_').lower()}.json"


# ── what she sees at a waypoint ──────────────────────────────────────────
def _look() -> dict:
    look = {"people": sum(1 for label, _ in (getattr(state, "cam1_detection_labels", None) or [])
                          if str(label).lower() == "person")}
    try:
        import haptics
        look["range_cm"] = haptics.closest_cm()
    except Exception:
        look["range_cm"] = None
    try:
        import cv2
        from kida_mind import frames
        frame, _ = frames.latest(3.0)
        if frame is not None:
            g = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (16, 9), interpolation=cv2.INTER_AREA)
            look["thumb"] = [int(v) for v in g.flatten()]
            look["brightness"] = round(float(g.mean()), 1)
    except Exception:
        pass
    return look


def compare(then: dict, now: dict) -> list:
    """What's different between two looks, as short phrases."""
    diffs = []
    if then.get("thumb") and now.get("thumb") and len(then["thumb"]) == len(now["thumb"]):
        d = sum(abs(a - b) for a, b in zip(then["thumb"], now["thumb"])) / len(then["thumb"])
        b0, b1 = then.get("brightness", 0), now.get("brightness", 0)
        if abs(b1 - b0) > DIFF_BRIGHT:
            diffs.append("it's much " + ("brighter" if b1 > b0 else "darker"))
        elif d > DIFF_VIEW:
            diffs.append("it looks different")
    p0, p1 = then.get("people", 0), now.get("people", 0)
    if p1 > p0:
        diffs.append("someone's there now")
    elif p0 > p1:
        diffs.append("the person who was there has gone")
    r0, r1 = then.get("range_cm"), now.get("range_cm")
    if r1 is not None and (r0 is None or r0 - r1 > DIFF_RANGE_CM):
        diffs.append("there's something in the way now")
    elif r0 is not None and (r1 is None or r1 - r0 > DIFF_RANGE_CM):
        diffs.append("something that used to be in the way is gone")
    return diffs


# ── recording ────────────────────────────────────────────────────────────
def _record_loop() -> None:
    import odometry
    while True:
        with _lock:
            rec = _recording
        if rec is None:
            return
        x, y, h = odometry.pose()
        lx, ly = odometry.to_local(rec["origin"], (x, y))
        last = rec["waypoints"][-1]
        moved = math.hypot(lx - last["x"], ly - last["y"])
        turned = abs((h - rec["origin"][2] - last["h"] + 180) % 360 - 180)
        if moved >= ROUTE_STEP_CM or (turned >= ROUTE_TURN_DEG and moved >= 10):
            with _lock:
                if _recording is rec:
                    rec["waypoints"].append({"x": round(lx, 1), "y": round(ly, 1),
                                             "h": round((h - rec["origin"][2] + 180) % 360 - 180, 1), "look": _look()})
        time.sleep(SAMPLE_S)


def record_start(name: str) -> bool:
    global _recording, _rec_thread
    import odometry
    import navigator
    if navigator.active():
        return False
    with _lock:
        if _recording is not None:
            return False
        _recording = {"name": _safe(name), "origin": odometry.pose(), "created": time.time(),
                      "waypoints": [{"x": 0.0, "y": 0.0, "h": 0.0, "look": _look()}]}
    _rec_thread = threading.Thread(target=_record_loop, daemon=True, name="RouteRecord")
    _rec_thread.start()
    state.systemStatus = f"Recording route '{_safe(name)}' — drive it"
    print(f"🗺️  Recording route '{_safe(name)}'")
    return True


def record_stop() -> dict | None:
    """Finish recording and save. Returns the route, or None if too short."""
    global _recording
    import odometry
    with _lock:
        rec, _recording = _recording, None
    if rec is None:
        return None
    x, y, h = odometry.pose()
    lx, ly = odometry.to_local(rec["origin"], (x, y))
    last = rec["waypoints"][-1]
    if math.hypot(lx - last["x"], ly - last["y"]) >= 10:
        rec["waypoints"].append({"x": round(lx, 1), "y": round(ly, 1),
                                 "h": round((h - rec["origin"][2] + 180) % 360 - 180, 1), "look": _look()})
    if len(rec["waypoints"]) < 2:
        state.systemStatus = "Route too short — not saved"
        return None
    ROUTES_DIR.mkdir(parents=True, exist_ok=True)
    route = {"name": rec["name"], "created": rec["created"], "waypoints": rec["waypoints"]}
    tmp = _path(rec["name"]).with_suffix(".tmp")
    tmp.write_text(json.dumps(route), encoding="utf-8")
    os.replace(tmp, _path(rec["name"]))
    state.systemStatus = f"Route '{rec['name']}' saved ({len(rec['waypoints'])} waypoints)"
    print(f"🗺️  Saved route '{rec['name']}' — {len(rec['waypoints'])} waypoints")
    return route


def recording() -> str | None:
    with _lock:
        return _recording["name"] if _recording else None


# ── library ──────────────────────────────────────────────────────────────
def load(name: str) -> dict | None:
    try:
        return json.loads(_path(name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def list_routes() -> list:
    out = []
    if ROUTES_DIR.is_dir():
        for f in sorted(ROUTES_DIR.glob("*.json")):
            try:
                r = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            wps = r.get("waypoints", [])
            length = sum(math.hypot(b["x"] - a["x"], b["y"] - a["y"]) for a, b in zip(wps, wps[1:]))
            out.append({"name": r.get("name", f.stem), "waypoints": len(wps), "length_cm": round(length)})
    return out


def delete(name: str) -> bool:
    try:
        _path(name).unlink()
        return True
    except OSError:
        return False


# ── replay / patrol ──────────────────────────────────────────────────────
def _notice(route_name: str, index: int, diffs: list) -> None:
    ordinal = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth", 7: "seventh",
               8: "eighth", 9: "ninth", 10: "tenth"}.get(index, f"number {index}")
    text = f"on the {route_name} route, near the {ordinal} stop, {' and '.join(diffs)}"
    _current["differences"].append(text)
    print(f"🗺️  Different: {text}")
    if len(_current["differences"]) > MAX_NOTICES:
        return
    try:
        import kida_mind_host
        if kida_mind_host.MIND is not None:
            kida_mind_host.MIND.notice(text)
    except Exception as e:
        print(f"[routes] mind notice: {e}")


def _drive(route: dict, loop: bool, origin=None) -> bool:
    import odometry
    import navigator
    # Every lap is laid out from the pose the patrol started at — after the
    # way back she's facing the other way, so "here" would be wrong.
    origin = origin or odometry.pose()
    wps = route["waypoints"]
    outward = [odometry.to_world(origin, (w["x"], w["y"])) for w in wps[1:]]
    back = [odometry.to_world(origin, (w["x"], w["y"])) for w in reversed(wps[:-1])]
    points, looks = (outward + back, list(range(1, len(wps))) + list(range(len(wps) - 2, -1, -1))) if loop \
        else (outward, list(range(1, len(wps))))

    def at_waypoint(i):
        wi = looks[i]
        then = wps[wi].get("look") or {}
        time.sleep(0.4)                                   # let the camera settle
        diffs = compare(then, _look())
        if diffs:
            _notice(route["name"], wi + 1, diffs)

    def done(result):
        if loop and _patrolling.is_set() and result == "arrived":
            _current["lap"] += 1
            threading.Timer(1.0, lambda: _drive(route, True, origin) or _patrolling.clear()).start()
        else:
            _patrolling.clear()
            state.systemStatus = f"Route '{route['name']}': {result}"

    return navigator.go(("patrol " if loop else "route ") + route["name"], points, on_waypoint=at_waypoint, on_done=done)


def play(name: str, patrol: bool = False) -> bool:
    """Replay (or patrol) a saved route from where she is now — put her where
    you started recording, facing the same way."""
    route = load(name)
    if not route or len(route.get("waypoints", [])) < 2 or recording():
        return False
    _current.update(name=route["name"], kind="patrol" if patrol else "replay", lap=0, differences=[])
    if patrol:
        _patrolling.set()
    ok = _drive(route, patrol)
    if not ok:
        _patrolling.clear()
    else:
        try:
            import daylog
            daylog.note("route")
        except Exception:
            pass
    return ok


def stop() -> None:
    import navigator
    _patrolling.clear()
    navigator.cancel("stopped")


def status() -> dict:
    import navigator
    return {"recording": recording(), "patrolling": _patrolling.is_set(),
            "current": dict(_current), "nav": navigator.status()}
