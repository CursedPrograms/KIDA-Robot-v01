# daylog.py — a short record of each day, and its summary
#
# Kept as she goes (memories/daylog/YYYY-MM-DD.json, gitignored):
#   how far she drove, and the furthest she got from home (odometry.py)
#   who she saw (face_id.py) and how many strangers
#   bumps, near-tips and rough rides (kida_mind_host.py)
#   her mood every 15 minutes (the inner life, if it's running)
#   conversations, photos taken, routes/patrols run, time spent in each mode
#
# summary(date) turns that into a few sentences — the web page's "Today"
# panel shows it with a mood strip, and the first time she dozes off after
# 9 pm it goes into her journal as a thought ("what did you do today?").

import json
import os
import threading
import time
from datetime import date as _date
from pathlib import Path

import state

DAYLOG_DIR     = Path(__file__).resolve().parent.parent / "memories" / "daylog"
MOOD_EVERY_S   = 15 * 60
SAVE_EVERY_S   = 60
JOURNAL_HOUR   = 21

_lock = threading.Lock()
_day: dict | None = None
_thread = None


def _today() -> str:
    return _date.today().isoformat()


def _path(day: str) -> Path:
    return DAYLOG_DIR / f"{day}.json"


def _blank(day: str) -> dict:
    return {"date": day, "driven_cm": 0.0, "furthest_cm": 0.0, "people": {}, "strangers": 0,
            "bumps": 0, "tips": 0, "shakes": 0, "mood": [], "conversations": 0, "photos": 0,
            "routes": 0, "modes": {}, "journaled": False}


def _load(day: str) -> dict:
    try:
        return {**_blank(day), **json.loads(_path(day).read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return _blank(day)


def _save(d: dict) -> None:
    DAYLOG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _path(d["date"]).with_suffix(".tmp")
    tmp.write_text(json.dumps(d), encoding="utf-8")
    os.replace(tmp, _path(d["date"]))


def _current() -> dict:
    """Today's record (rolls over at midnight, saving yesterday first)."""
    global _day
    t = _today()
    if _day is None or _day["date"] != t:
        if _day is not None:
            _save(_day)
        _day = _load(t)
    return _day


# ── things that happen ───────────────────────────────────────────────────
def note(kind: str, n: int = 1) -> None:
    """kind: "bump" | "tip" | "shake" | "photo" | "route" | "conversation"."""
    key = {"bump": "bumps", "tip": "tips", "shake": "shakes", "photo": "photos",
           "route": "routes", "conversation": "conversations"}.get(kind)
    if key:
        with _lock:
            _current()[key] += n


def note_person(name) -> None:
    with _lock:
        d = _current()
        if name:
            d["people"][name] = d["people"].get(name, 0) + 1
        else:
            d["strangers"] += 1


# ── the background tally ─────────────────────────────────────────────────
def _loop() -> None:
    import odometry
    last_driven = odometry.distance_driven()
    last_mood = last_save = 0.0
    last_tick = time.monotonic()
    last_conv = None
    while True:
        time.sleep(5)
        now = time.monotonic()
        try:
            with _lock:
                d = _current()
                driven = odometry.distance_driven()
                d["driven_cm"] += max(0.0, driven - last_driven)
                last_driven = driven
                d["furthest_cm"] = max(d["furthest_cm"], odometry.distance_to_home())
                mode = getattr(getattr(state, "drive_mode", None), "name", "?")
                d["modes"][mode] = round(d["modes"].get(mode, 0.0) + (now - last_tick) / 60.0, 2)
            last_tick = now

            import kida_mind_host
            mind = kida_mind_host.MIND
            if mind is not None:
                if last_conv is not None and mind.conversations > last_conv:
                    note("conversation", mind.conversations - last_conv)
                last_conv = mind.conversations
                if now - last_mood >= MOOD_EVERY_S:
                    last_mood = now
                    with _lock:
                        _current()["mood"].append({"t": time.strftime("%H:%M"), "v": round(mind.mood.valence, 2),
                                                   "label": mind.mood_label()})
            if now - last_save >= SAVE_EVERY_S:
                last_save = now
                with _lock:
                    _save(_current())
        except Exception as e:
            print(f"[daylog] {e}")


def start() -> None:
    global _thread
    if _thread is None:
        _thread = threading.Thread(target=_loop, daemon=True, name="DayLog")
        _thread.start()


# ── the summary ──────────────────────────────────────────────────────────
def _metres(cm: float) -> str:
    m = cm / 100.0
    return f"{m:.0f} metres" if m >= 10 else f"{m:.1f} metres"


def _count(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _times(n: int) -> str:
    return {1: "once", 2: "twice"}.get(n, f"{n} times")


def summary_text(d: dict) -> str:
    bits = []
    if d["driven_cm"] >= 50:
        bits.append(f"I drove {_metres(d['driven_cm'])}"
                    + (f" and got as far as {_metres(d['furthest_cm'])} from home." if d["furthest_cm"] >= 100 else "."))
    else:
        bits.append("I barely moved today.")
    people = sorted(d["people"], key=lambda n: -d["people"][n])
    if people or d["strangers"]:
        who = ", ".join(people[:-1]) + (" and " if len(people) > 1 else "") + (people[-1] if people else "")
        s = f"I saw {who}" if people else "I didn't see anyone I know"
        if d["strangers"]:
            s += f"{', and ' if people else ', but '}{_count(d['strangers'], 'stranger')}"
        bits.append(s + ".")
    knocks = []
    if d["bumps"]:
        knocks.append(f"bumped into things {_times(d['bumps'])}")
    if d["tips"]:
        knocks.append(f"nearly tipped over {_times(d['tips'])}")
    if d["shakes"]:
        knocks.append(f"had {_count(d['shakes'], 'rough ride')}")
    if knocks:
        bits.append("I " + ", ".join(knocks) + ".")
    moods = [m["label"] for m in d["mood"]]
    if moods:
        common = max(set(moods), key=moods.count)
        worst = min(d["mood"], key=lambda m: m["v"])
        s = f"Mostly I felt {common}"
        if worst["label"] != common and worst["v"] < 0:
            s += f", though I was {worst['label']} around {worst['t']}"
        bits.append(s + ".")
    extras = []
    if d["conversations"]:
        extras.append(_count(d["conversations"], "conversation"))
    if d["photos"]:
        extras.append(_count(d["photos"], "photo"))
    if d["routes"]:
        extras.append(_count(d["routes"], "route") + " driven")
    if extras:
        bits.append("There were " + ", ".join(extras) + ".")
    modes = {k: v for k, v in d["modes"].items() if k not in ("?",)}
    if modes:
        top = max(modes, key=modes.get)
        if modes[top] >= 10:
            bits.append(f"Most of the day I was in {top.replace('_', ' ').lower()} mode.")
    return " ".join(bits)


def day(day: str | None = None) -> dict:
    """A day's record plus its summary (today's is live)."""
    day = day or _today()
    with _lock:
        d = dict(_current()) if day == _today() else _load(day)
    return {**d, "summary": summary_text(d)}


def days(limit: int = 30) -> list:
    if not DAYLOG_DIR.is_dir():
        return [_today()]
    found = sorted({p.stem for p in DAYLOG_DIR.glob("*.json")} | {_today()}, reverse=True)
    return found[:limit]


def maybe_journal() -> None:
    """Call when she dozes off: after 9 pm, today's summary goes into her
    journal once, as a thought she can be asked about."""
    if time.localtime().tm_hour < JOURNAL_HOUR:
        return
    with _lock:
        d = _current()
        if d["journaled"]:
            return
        d["journaled"] = True
        text = summary_text(d)
    try:
        from kida_mind.reflection import add_thought
        add_thought("Today: " + text, "thought")
    except Exception:
        pass
