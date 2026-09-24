# kida_mind_host.py — wires KIDA's inner life (scripts/kida_mind) into the robot
#
# The mind itself is hardware-free (ported from DREAM's dream_mind). This is
# the robot side, the part DREAM's dream.py did for DREAM:
#
#   speaking   the mind's initiatives go through kida_chat_wakeword's task
#              queue (say()), so they never talk over a reply in progress
#   sleeping   KIDA "sleeps" in IDLE mode: after a quiet spell (shorter when
#              she's tired - Mind.adaptive_sleep_timeout), or when the mind
#              decides to. Asleep, she consolidates memories (once - no
#              Anything that's for her wakes her - her name, typed text, a
#              web/joystick/keyboard drive, a mode change - and she may tell
#              dreaming, which would cost the Pi too much). Motors, safety and the wake word are
#              untouched while she sleeps.
#   presence   people cam-1's IMX500 (and cam-0 YOLO, when it's on) sees, plus
#              recent interaction → PRESENT / ABSENT. The PIR firing while
#              nobody's in view and she isn't moving → MOTION.
#   her body   bumps (ball switch while driving), tipping (haptics' tilt),
#              shaking (vibration_guard) and being driven → Mind.on_body_event
#
# Optional, like DREAM's: if the mind can't load, KIDA runs exactly as before.

import threading
import time

import state
from state import DriveMode

SLEEP_IDLE_S     = 30 * 60   # quiet this long (adjusted by how tired she is) → she dozes off
POLL_S           = 1.0
PRESENT_HOLD_S   = 90        # someone seen this recently still counts as here
INTERACTION_HOLD_S = 120     # ...and so does someone who just spoke to / drove her
MOTION_EVERY_S   = 120
BUMP_EVERY_S     = 10
TIP_EVERY_S      = 30

try:
    from kida_mind import get_mind, llm as mind_llm, voice as mind_voice, facts as mind_facts
    MIND = get_mind()
except Exception as _mind_error:   # numpy/cv2 missing, a bug - KIDA must still run
    MIND = mind_llm = mind_voice = mind_facts = None
    print(f"⚠️  Inner life unavailable ({_mind_error}) — running without it")

_say = None                  # kida_chat_wakeword.say, set by start()
_lock = threading.Lock()
_sleeping = False
_mode_before_sleep = None
_busy = 0                    # >0 while the voice pipeline is handling something
_last_activity = time.time()
_last_moved_ts = 0.0
_last_person_ts = 0.0
_present = False
_people = 0
_last_motion = _last_bump = _last_tip = 0.0
_prev_ball = _prev_vibe = _prev_tip = False


# ── things the rest of KIDA calls ────────────────────────────────────────
def note_activity(kind: str = "other") -> None:
    """Someone did something with/to her. kind "drive" also counts as being
    driven (her body moved) — web_bridge and event_handler call this."""
    global _last_activity, _last_moved_ts
    now = time.time()
    _last_activity = now
    if kind == "drive":
        _last_moved_ts = now
        if MIND:
            MIND.on_body_event("drive")
        if _sleeping:
            wake()


class busy:
    """with kida_mind_host.busy(): ... — she's in the middle of something
    (listening/thinking/speaking), so she won't start a remark of her own."""
    def __enter__(self):
        global _busy
        _busy += 1

    def __exit__(self, *exc):
        global _busy
        _busy = max(0, _busy - 1)


def is_sleeping() -> bool:
    return _sleeping


def enter_sleep() -> None:
    """Close her eyes: IDLE mode (motors stopped, idle overlay) while she
    consolidates her memories. Only from KEYBOARD/IDLE — never out from under a
    self-driving mode."""
    global _sleeping, _mode_before_sleep
    import mode_manager
    with _lock:
        if _sleeping:
            return
        mode = mode_manager.current_mode()
        if mode not in (DriveMode.KEYBOARD, DriveMode.IDLE):
            return
        _sleeping = True
        _mode_before_sleep = mode
    print("💤 KIDA is falling asleep…")
    try:                                   # after 9 pm, today goes into her journal
        import daylog
        daylog.maybe_journal()
    except Exception:
        pass
    if mode != DriveMode.IDLE:
        mode_manager.set_mode(DriveMode.IDLE)


def wake(blocking: bool = False) -> str | None:
    """Open her eyes. Her mode comes back straight away (so a drive command
    that woke her works); finishing the night - which can take a few seconds
    for the sleep thread - happens after.

    blocking=True (the voice worker, which can wait): returns what she has
    to say about the night, or None. Otherwise that line is queued with say()."""
    global _sleeping, _mode_before_sleep
    with _lock:
        if not _sleeping:
            return None
        _sleeping = False
        restore, _mode_before_sleep = _mode_before_sleep, None
    print("☀️  KIDA woke up")
    import mode_manager
    if restore == DriveMode.KEYBOARD and mode_manager.current_mode() == DriveMode.IDLE:
        mode_manager.set_mode(DriveMode.KEYBOARD)
    if MIND is None:
        return None
    if blocking:
        return MIND.end_sleep()

    def finish():
        line = MIND.end_sleep()
        if line and _say:
            _say(line)
    threading.Thread(target=finish, daemon=True, name="kida-mind-wake").start()
    return None


def _on_mode_change(new_mode) -> None:
    if new_mode == DriveMode.IDLE:
        return                     # that's her own sleep (or you parking her) — not a wake-up
    note_activity("mode")
    if _sleeping:
        wake()


# ── what the mind asks of the host ───────────────────────────────────────
def _host_state() -> dict:
    return {
        "sleeping": _sleeping,
        "state": "busy" if _busy else "idle",
        "present": _present,
        "people": _people,
        "last_moved_ts": _last_moved_ts,
    }


def _sensor(cmd: str) -> bool:
    from arduino import send_command
    send_command("dev01", cmd)
    return True


# ── the watcher: presence, body events, falling asleep ───────────────────
def _count_people() -> int:
    n = sum(1 for label, _ in (getattr(state, "cam1_detection_labels", None) or [])
            if str(label).lower() == "person")
    if time.monotonic() - getattr(state, "detection_boxes_ts", 0.0) < 2.0:   # cam-0 YOLO, when it's running
        n = max(n, sum(1 for label, _ in (state.detection_labels or []) if str(label).lower() == "person"))
    return n


def _daylog(kind: str) -> None:
    try:
        import daylog
        daylog.note(kind)
    except Exception:
        pass


def _watch_body(now: float) -> bool:
    global _prev_ball, _prev_vibe, _prev_tip, _last_bump, _last_tip
    from sensor_assist import _parse_int
    import web_bridge

    driving = web_bridge.is_driving() or now - _last_moved_ts < 2.0
    ball = _parse_int(state.ballSwitchValue) == 1
    if ball and not _prev_ball and driving and now - _last_bump > BUMP_EVERY_S:
        _last_bump = now
        MIND.on_body_event("bump")
        _daylog("bump")
    _prev_ball = ball

    try:
        import haptics
        tilt = haptics._tilt_deg()
        tipping = tilt is not None and tilt > haptics.TIP_DEG
    except Exception:
        tipping = False
    if tipping and not _prev_tip and now - _last_tip > TIP_EVERY_S:
        _last_tip = now
        MIND.on_body_event("tip")
        _daylog("tip")
    _prev_tip = tipping

    vibe = bool(getattr(state, "vibration_active", False))
    if vibe and not _prev_vibe:
        MIND.on_body_event("shake")
        _daylog("shake")
    _prev_vibe = vibe
    return driving


def _watch() -> None:
    global _present, _people, _last_person_ts, _last_motion
    import mode_manager
    from sensor_assist import _parse_int
    while True:
        time.sleep(POLL_S)
        try:
            now = time.time()
            _people = _count_people()
            if _people:
                _last_person_ts = now
            present = (now - _last_person_ts < PRESENT_HOLD_S) or (now - _last_activity < INTERACTION_HOLD_S)
            if present != _present:
                _present = present
                MIND.on_sensor("PRESENT" if present else "ABSENT")

            driving = _watch_body(now)

            calm_mode = mode_manager.current_mode() in (DriveMode.KEYBOARD, DriveMode.IDLE)
            if (_parse_int(state.motionValue) == 1 and not _people and not driving and calm_mode
                    and now - _last_motion > MOTION_EVERY_S):
                _last_motion = now
                MIND.on_sensor("MOTION")

            label = MIND.mood_label()
            state.mind_label = f"{label} (asleep)" if _sleeping else label

            quiet_for = now - _last_activity
            if (not _sleeping and not _busy and calm_mode and not driving
                    and quiet_for >= MIND.adaptive_sleep_timeout(SLEEP_IDLE_S)):
                print(f"💤 Quiet for {quiet_for / 60:.0f} min — KIDA dozes off")
                enter_sleep()
        except Exception as e:   # the watcher must not die of a bug
            print(f"[mind host] {e}")


def start(say) -> bool:
    """Wake the mind. say(text): queue a line for KIDA to speak (serialized
    with her replies). Returns whether the mind is running."""
    global _say
    if MIND is None:
        return False
    _say = say
    import mode_manager
    mode_manager.register_on_mode_change(_on_mode_change)
    owner = MIND.start(host={
        "speak": lambda text: (say(text), True)[1],
        "sleep": enter_sleep,
        "state": _host_state,
        "sensor": _sensor,
    })
    if owner:
        threading.Thread(target=_watch, daemon=True, name="kida-mind-host").start()
        print("🧠 Inner life started — mood, needs and memory are running")
    else:
        print("🧠 Another KIDA process already runs the inner life — this one stays passive")
    return owner


def stop() -> None:
    if MIND:
        MIND.stop()
