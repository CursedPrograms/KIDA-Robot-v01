# navigator.py — drive to a point (or along a list of them) using odometry
#
# Used by "go home" (back to where she started — odometry's (0, 0)) and by
# routes.py (replaying a recorded route / patrolling it).
#
#   facing far off the target  → turn on the spot (tank turn)
#   roughly facing it          → drive, steering proportionally
#   within REACH_CM            → next waypoint
#
# Safety — she stops and the task ends ("aborted: <why>") when:
#   - you touch any drive control, press stop, or change mode (cancel())
#   - something is closer than OBSTACLE_CM ahead for longer than BLOCKED_WAIT_S
#     (she waits first — a person stepping past shouldn't end a patrol)
#   - the bump switch fires, or the motors get locked
#   - a waypoint takes longer than WAYPOINT_TIMEOUT_S (lost, stuck, slipping)
# Only runs in KEYBOARD mode, and only one task at a time.
#
# Accuracy is whatever odometry's is — see odometry.py. Tune the PWMs below
# for your motors if she crawls or overshoots.

import math
import threading
import time

import state

DRIVE_PWM          = 170
TURN_PWM           = 150
MIN_PWM            = 90       # the motors stall below this
STEER_GAIN         = 2.0      # PWM per degree of heading error while driving
TURN_IN_PLACE_DEG  = 30       # heading error beyond which she turns on the spot first
REACH_CM           = 15
OBSTACLE_CM        = 25
BLOCKED_WAIT_S     = 8.0
WAYPOINT_TIMEOUT_S = 30.0
LOOP_S             = 0.1

_lock = threading.Lock()
_thread: threading.Thread | None = None
_cancel = threading.Event()
_status = {"active": False, "task": "", "index": 0, "count": 0, "result": ""}


def _wrap(deg: float) -> float:
    return (deg + 180.0) % 360.0 - 180.0


def _set_status(**kw) -> None:
    with _lock:
        _status.update(kw)


def status() -> dict:
    with _lock:
        return dict(_status)


def active() -> bool:
    return status()["active"]


def cancel(reason: str = "stopped") -> None:
    """Stop whatever she's navigating (safe to call when nothing is)."""
    if active():
        _set_status(result=f"aborted: {reason}")
        _cancel.set()


def _motors(left: int, right: int) -> None:
    from arduino import set_left_motor, set_right_motor
    set_left_motor(left)
    set_right_motor(right)


def _stop() -> None:
    from arduino import send_command, set_stopped_lights
    send_command("dev00", "STOP")
    set_stopped_lights()


def _blocked() -> bool:
    try:
        import haptics
        d = haptics.closest_cm()
        return d is not None and d < OBSTACLE_CM
    except Exception:
        return False


def _bumped() -> bool:
    try:
        from sensor_assist import _parse_int
        return _parse_int(state.ballSwitchValue) == 1
    except Exception:
        return False


def _drive_to(target: tuple, deadline: float) -> str | None:
    """Drive to one world point. Returns None on arrival, else why it stopped."""
    import odometry
    import mode_manager
    blocked_since = None
    while True:
        if _cancel.is_set():
            return "cancelled"
        if not mode_manager.is_keyboard():
            return "mode changed"
        if state.motor_lock:
            return "motors locked"
        if _bumped():
            return "bumped into something"
        if time.monotonic() > deadline:
            return "took too long (stuck or lost?)"

        x, y, heading = odometry.pose()
        dx, dy = target[0] - x, target[1] - y
        dist = math.hypot(dx, dy)
        if dist < REACH_CM:
            return None
        err = _wrap(math.degrees(math.atan2(dy, dx)) - heading)   # + = target is to her left

        if abs(err) > TURN_IN_PLACE_DEG:
            blocked_since = None
            t = TURN_PWM if err > 0 else -TURN_PWM                # CCW: left track back, right forward
            _motors(-t, t)
        elif _blocked():
            _motors(0, 0)
            blocked_since = blocked_since or time.monotonic()
            _set_status(result="waiting — something's in the way")
            if time.monotonic() - blocked_since > BLOCKED_WAIT_S:
                return "blocked"
        else:
            blocked_since = None
            base = DRIVE_PWM if dist > 40 else max(MIN_PWM + 20, int(DRIVE_PWM * dist / 40))
            corr = STEER_GAIN * err
            left = int(max(MIN_PWM, min(255, base - corr)))
            right = int(max(MIN_PWM, min(255, base + corr)))
            _motors(left, right)
        time.sleep(LOOP_S)


def _run(task: str, points: list, on_waypoint, on_done, final_heading=None) -> None:
    from arduino import set_driving_lights
    result = "arrived"
    try:
        set_driving_lights()
        for i, p in enumerate(points):
            _set_status(index=i + 1)
            why = _drive_to(p, time.monotonic() + WAYPOINT_TIMEOUT_S)
            if why:
                result = f"aborted: {why}"
                break
            if on_waypoint:
                try:
                    on_waypoint(i)
                except Exception as e:
                    print(f"[navigator] waypoint hook: {e}")
        if final_heading is not None and not result.startswith("aborted") and not _cancel.is_set():
            _face(final_heading)
    finally:
        _stop()
        if _cancel.is_set():                 # cancel(reason) already wrote why
            prior = status()["result"]
            result = prior if prior.startswith("aborted") else "aborted: cancelled"
        _set_status(active=False, result=result)
        state.systemStatus = f"Nav {task}: {result}"
        print(f"🧭 {task}: {result}")
        if on_done:
            try:
                on_done(result)
            except Exception as e:
                print(f"[navigator] done hook: {e}")


def go(task: str, points: list, on_waypoint=None, on_done=None, final_heading=None) -> bool:
    """Drive through `points` ([(x, y) world cm, ...]) in the background.
    on_waypoint(i) after reaching each; on_done(result) at the end.
    Returns False if she can't start (not KEYBOARD mode, locked, or busy)."""
    global _thread
    import mode_manager
    if not points or not mode_manager.is_keyboard() or state.motor_lock:
        return False
    with _lock:
        if _status["active"]:
            return False
        _status.update(active=True, task=task, index=0, count=len(points), result="")
    _cancel.clear()
    _thread = threading.Thread(target=_run, args=(task, points, on_waypoint, on_done, final_heading),
                               daemon=True, name="Navigator")
    _thread.start()
    print(f"🧭 {task}: {len(points)} waypoint(s)")
    return True


def go_home(on_done=None) -> bool:
    """Back to where she started (odometry's origin), then face the way she started."""
    import odometry
    if odometry.distance_to_home() < REACH_CM:
        return False
    return go("go home", [(0.0, 0.0)], on_done=on_done, final_heading=0.0)


def _face(target_heading: float, timeout_s: float = 6.0) -> None:
    """Turn on the spot to a heading (best effort, blocking)."""
    import odometry
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline and not _cancel.is_set():
        err = _wrap(target_heading - odometry.pose()[2])
        if abs(err) < 8:
            break
        t = TURN_PWM if err > 0 else -TURN_PWM
        _motors(-t, t)
        time.sleep(LOOP_S)
    _stop()


def _on_mode_change(new_mode) -> None:
    from state import DriveMode
    if new_mode != DriveMode.KEYBOARD:
        cancel("mode changed")


def init() -> None:
    import mode_manager
    mode_manager.register_on_mode_change(_on_mode_change)
