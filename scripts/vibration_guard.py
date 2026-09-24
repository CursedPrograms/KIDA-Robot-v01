# vibration_guard.py — treat rapid ball-switch toggles as a vibration/shock
# event and slow down until things settle.
#
# The ball switch (BALL_PIN on dev01, scripts/arduino/arduino01/ardiuno01/ardiuno01.ino)
# is a tilt switch: a loose metal ball rolls to bridge or break contact. A
# single steady reading only tells you the robot's tilt. Under vibration or
# a shock, the ball bounces and the contact flickers rapidly between 0/1
# several times inside a second — so vibration shows up as toggle *rate*,
# not the raw value. dev01 reports BALL every ~250ms, so we watch the last
# few reads for a burst of flips.

import threading
import time
from collections import deque

import state
import config
import arduino
import voice_engine

POLL_INTERVAL_S  = 0.1
WINDOW_S         = 1.5   # look at toggles within this trailing window
TOGGLE_THRESHOLD = 4     # this many flips inside WINDOW_S => vibration
SLOWDOWN_FACTOR  = 0.6   # keep 60% of speed (was 50% — too aggressive a cut)
COOLDOWN_S       = 3.0   # no new toggles for this long before restoring speed

_thread: threading.Thread | None = None
_stop_event = threading.Event()


def _loop():
    history = deque()   # timestamps of ball-value flips
    last_value = None
    triggered = False
    baseline_speed = None
    last_toggle_t = 0.0

    while not _stop_event.wait(POLL_INTERVAL_S):
        raw = getattr(state, "ballSwitchValue", None)
        if raw in (None, "-"):
            continue
        value = str(raw)
        now = time.monotonic()

        if last_value is not None and value != last_value:
            history.append(now)
            last_toggle_t = now
        last_value = value

        while history and now - history[0] > WINDOW_S:
            history.popleft()

        if not triggered and len(history) >= TOGGLE_THRESHOLD:
            triggered = True
            state.vibration_active = True
            baseline_speed = int(getattr(state, "motorSpeedValue", None) or config.DEFAULT_SPEED)
            reduced = max(config.MIN_SPEED, int(baseline_speed * SLOWDOWN_FACTOR))
            arduino.set_motor_speed(reduced)
            print(f"📳 Vibration detected — slowing {baseline_speed} → {reduced}")
            voice_engine.speak_line("Whoa, easy! I felt that. Slowing down.", key="vibration_alert")

        elif triggered and (now - last_toggle_t) > COOLDOWN_S:
            triggered = False
            state.vibration_active = False
            if baseline_speed:
                arduino.set_motor_speed(baseline_speed)
                print(f"📳 Vibration settled — restoring speed to {baseline_speed}")
            baseline_speed = None


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_loop, daemon=True)
    _thread.start()
    print("📳 Vibration guard started")


def stop() -> None:
    _stop_event.set()
