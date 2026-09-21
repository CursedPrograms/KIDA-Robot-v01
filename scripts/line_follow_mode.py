# line_follow_mode.py — Line follower mode with proper thread management
#
# This thread is the sole source of dev00 motor commands while
# LINE_FOLLOWER is active, so ball-switch/proximity safety checks run
# inline here rather than in sensor_assist.py — a STOP sent from a
# separate thread would just get overwritten by this loop's own next
# FORWARD/LEFT/RIGHT tick 50ms later.

import threading
import time
import logging

import state
from arduino import send_command

logger = logging.getLogger(__name__)

LOOP_DELAY     = 0.05   # 50 ms
LINE_THRESHOLD = 500
STOP_DIST_CM   = 8      # matches sensor_assist.STOP_DIST_CM, kept in sync intentionally

_stop_event = threading.Event()
_thread: threading.Thread | None = None


def _parse_sensor(value):
    if value is None:
        return None
    try:
        if isinstance(value, str) and ": " in value:
            return int(value.split(": ")[1])
        return int(float(str(value)))
    except (ValueError, IndexError, AttributeError):
        return None


def _read_sensors():
    return (
        _parse_sensor(getattr(state, 'lfLeftValue', None)),
        _parse_sensor(getattr(state, 'lfMidValue',  None)),
        _parse_sensor(getattr(state, 'lfRightValue', None)),
    )


def _safety_stop_reason() -> str | None:
    """Ball-switch collision or too-close obstacle — returns a status
    string if the line-following command this tick should be overridden
    with STOP, else None."""
    if _parse_sensor(getattr(state, 'ballSwitchValue', None)) == 1:
        return "⚠ Collision — bump stop"
    dists = [
        v for v in (
            _parse_sensor(getattr(state, 'laserValue', None)),
            _parse_sensor(getattr(state, 'ultrasonic0Value', None)),
            _parse_sensor(getattr(state, 'ultrasonic1Value', None)),
        )
        if v is not None and v > 0
    ]
    if dists and min(dists) < STOP_DIST_CM:
        return f"⚠ Too close ({min(dists)} cm)"
    return None


def _detect_position(left, middle, right):
    def on(v):
        return v is not None and v > LINE_THRESHOLD
    l, m, r = on(left), on(middle), on(right)
    if m:
        if l and r:  return "CENTER_WIDE"
        if l:        return "SLIGHT_LEFT"
        if r:        return "SLIGHT_RIGHT"
        return "CENTER"
    if l and not r:  return "LEFT"
    if r and not l:  return "RIGHT"
    return "LOST"


# arduino00.ino only recognizes FORWARD/BACKWARD/LEFT/RIGHT/STOP — it has no
# gentler "slight" turn commands, so SLIGHT_LEFT/SLIGHT_RIGHT below used to
# map to command strings the firmware silently ignored (found while wiring
# in the safety checks above: drift correction was a no-op). LEFT/RIGHT are
# the closest available substitute.
_CMD_MAP = {
    "CENTER":       "FORWARD",
    "CENTER_WIDE":  "FORWARD",
    "SLIGHT_LEFT":  "LEFT",
    "SLIGHT_RIGHT": "RIGHT",
    "LEFT":         "LEFT",
    "RIGHT":        "RIGHT",
    "LOST":         "STOP",
}


def _run():
    logger.info("Line follower thread started")
    state.systemStatus = "LineFollower: RUNNING"
    while not _stop_event.is_set():
        try:
            reason = _safety_stop_reason()
            if reason:
                send_command("dev00", "STOP")
                state.systemStatus = f"LF: {reason}"
                time.sleep(LOOP_DELAY)
                continue

            l, m, r = _read_sensors()
            pos = _detect_position(l, m, r)
            cmd = _CMD_MAP.get(pos, "STOP")
            send_command("dev00", cmd)
            state.systemStatus = f"LF: {cmd} | {pos} | L={l} M={m} R={r}"
        except Exception as e:
            logger.error("Line follower step error: %s", e)
            send_command("dev00", "STOP")
        time.sleep(LOOP_DELAY)
    send_command("dev00", "STOP")
    state.systemStatus = "LineFollower: STOPPED"
    logger.info("Line follower thread stopped")


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_run, daemon=True, name="LineFollower")
    _thread.start()


def stop() -> None:
    _stop_event.set()
    if _thread:
        _thread.join(timeout=1.0)
