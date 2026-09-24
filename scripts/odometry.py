# odometry.py — where KIDA thinks she is: (x, y) in cm and a heading
#
# She has no wheel encoders, so this is dead reckoning from two sources:
#
#   distance  what the Pi told the motors to do. Every dev00 command goes
#             through arduino.send_command(), which calls note_command() here,
#             so FORWARD/BACKWARD/LEFT/RIGHT/STOP (at the current SPEED) and
#             LMOTOR/RMOTOR (tank / curves / joystick) all become a commanded
#             speed per track. Speed = CM_PER_S_AT_FULL * pwm / 255 — measure
#             that once (drive forward 3 s at speed 255, tape-measure it).
#   heading   the MPU6050 gyro's yaw rate, integrated — far better than
#             guessing from the tracks, which slip on every turn. Its bias is
#             re-learned whenever the motors are stopped. Without an MPU, the
#             track speeds are used instead (skid-steer model).
#
# Frame: she starts at (0, 0) facing heading 0 ("home"). +x is her starting
# forward, +y her starting left, heading is counter-clockwise degrees.
#
# Blind spot: in AUTONOMOUS the Arduino drives itself and never says how, so
# only the heading is tracked then and the pose is marked uncertain.
#
# ⚠️ Dead reckoning drifts — expect ~10% distance error, more on carpet.
# Good enough for "go back where you started" across a room, and for putting
# LIDAR sweeps in roughly the right place; not for millimetres.

import math
import threading
import time

import state

CM_PER_S_AT_FULL  = 45.0    # forward speed at PWM 255 — measure yours (see above)
TRACK_WIDTH_CM    = 14.0    # centre-to-centre of the tracks (skid-steer fallback only)
SKID_TURN_FACTOR  = 0.6     # tracks slip when turning: only this much of the ideal rotation happens
STALL_PWM         = 60      # below this the motors don't actually turn
GYRO_AXIS         = "mpu_gz"   # yaw axis, for an MPU mounted flat
GYRO_SIGN         = 1.0     # flip to -1 if turning LEFT makes the heading go down
GYRO_DEADBAND_DPS = 0.8     # ignore rate noise below this (deg/s)
TRAIL_STEP_CM     = 10.0    # the path is sampled this often
TRAIL_MAX         = 2000
LOOP_S            = 0.05

_lock = threading.Lock()
_speed = 255                 # firmware's robotState.motorSpeed (SPEED:<n>)
_left = _right = 0           # commanded PWM per track, -255..255
_tank = False                # last command was LMOTOR/RMOTOR (firmware keeps both)
_autonomous = False
_x = _y = 0.0
_heading = 0.0               # degrees, CCW
_distance_today = 0.0
_gyro_bias = 0.0
_stopped_since = time.monotonic()
_trail: list = [(0.0, 0.0)]
_uncertain = False
_thread = None


def note_command(cmd: str) -> None:
    """Called by arduino.send_command() for every dev00 command actually sent."""
    global _speed, _left, _right, _tank, _autonomous, _stopped_since
    cmd = cmd.strip().upper()
    with _lock:
        was_moving = bool(_left or _right)
        if cmd.startswith("SPEED:"):
            try:
                _speed = max(0, min(255, int(cmd[6:])))
            except ValueError:
                pass
            return                   # applies to the next preset, not the current motion
        if cmd.startswith("LMOTOR:") or cmd.startswith("RMOTOR:"):
            try:
                v = max(-255, min(255, int(cmd[7:])))
            except ValueError:
                return
            if not _tank:
                _left = _right = 0   # a preset was running: tank mode starts from zero
            _tank = True
            if cmd.startswith("L"):
                _left = v
            else:
                _right = v
        elif cmd in ("FORWARD", "BACKWARD", "LEFT", "RIGHT", "STOP"):
            _tank = False
            s = _speed
            _left, _right = {"FORWARD": (s, s), "BACKWARD": (-s, -s), "LEFT": (-s, s),
                             "RIGHT": (s, -s), "STOP": (0, 0)}[cmd]
        elif cmd == "AUTO_ON":
            _autonomous = True
        elif cmd == "AUTO_OFF":
            _autonomous = False
            _left = _right = 0
        else:
            return
        if was_moving and not (_left or _right):
            _stopped_since = time.monotonic()


def _track_speed(pwm: int) -> float:
    if abs(pwm) < STALL_PWM:
        return 0.0
    return CM_PER_S_AT_FULL * pwm / 255.0


def _gyro_rate() -> float | None:
    if not getattr(state, "mpu_available", False):
        return None
    try:
        return float(getattr(state, GYRO_AXIS)) * GYRO_SIGN
    except (TypeError, ValueError):
        return None


def _step(dt: float) -> None:
    global _x, _y, _heading, _gyro_bias, _distance_today, _uncertain
    with _lock:
        left, right, auto = _left, _right, _autonomous
        still_for = time.monotonic() - _stopped_since if not (left or right) else 0.0
    rate = _gyro_rate()
    vl, vr = _track_speed(left), _track_speed(right)

    if rate is not None:
        if still_for > 1.0 and not auto:              # parked: learn the gyro's bias
            _gyro_bias += (rate - _gyro_bias) * 0.05
        w = rate - _gyro_bias
        dtheta = w * dt if abs(w) > GYRO_DEADBAND_DPS else 0.0
    else:
        dtheta = math.degrees((vr - vl) / TRACK_WIDTH_CM * SKID_TURN_FACTOR) * dt

    if auto:
        _uncertain = True                             # heading only; distance unknown
        v = 0.0
    else:
        v = (vl + vr) / 2.0

    h = math.radians(_heading + dtheta / 2.0)
    with _lock:
        _heading = (_heading + dtheta + 180.0) % 360.0 - 180.0
        _x += v * dt * math.cos(h)
        _y += v * dt * math.sin(h)
        _distance_today += abs(v) * dt
        lx, ly = _trail[-1]
        if math.hypot(_x - lx, _y - ly) >= TRAIL_STEP_CM:
            _trail.append((round(_x, 1), round(_y, 1)))
            if len(_trail) > TRAIL_MAX:
                del _trail[: len(_trail) - TRAIL_MAX]
        state.pose = (round(_x, 1), round(_y, 1), round(_heading, 1))


def _loop() -> None:
    last = time.monotonic()
    while True:
        time.sleep(LOOP_S)
        now = time.monotonic()
        try:
            _step(now - last)
        except Exception as e:
            print(f"[odometry] {e}")
        last = now


def start() -> None:
    global _thread
    if _thread is None:
        _thread = threading.Thread(target=_loop, daemon=True, name="Odometry")
        _thread.start()
        print("🧭 Odometry started (dead reckoning + gyro heading)")


# ── reading it ───────────────────────────────────────────────────────────
def pose() -> tuple[float, float, float]:
    """(x_cm, y_cm, heading_deg) — heading CCW from her starting direction."""
    with _lock:
        return _x, _y, _heading


def is_moving() -> bool:
    with _lock:
        return bool(_left or _right) or _autonomous


def commanded() -> tuple[int, int]:
    with _lock:
        return _left, _right


def distance_to_home() -> float:
    with _lock:
        return math.hypot(_x, _y)


def distance_driven() -> float:
    """cm driven since start (or since reset_distance())."""
    with _lock:
        return _distance_today


def reset_distance() -> float:
    global _distance_today
    with _lock:
        d, _distance_today = _distance_today, 0.0
    return d


def trail() -> list:
    with _lock:
        return list(_trail)


def set_home() -> None:
    """Call where she is now 'home': pose back to (0, 0, 0), trail cleared."""
    global _x, _y, _heading, _trail, _uncertain
    with _lock:
        _x = _y = _heading = 0.0
        _trail = [(0.0, 0.0)]
        _uncertain = False
        state.pose = (0.0, 0.0, 0.0)


def summary() -> dict:
    with _lock:
        return {"x": round(_x, 1), "y": round(_y, 1), "heading": round(_heading, 1),
                "home_cm": round(math.hypot(_x, _y)), "driven_cm": round(_distance_today),
                "uncertain": _uncertain, "moving": bool(_left or _right) or _autonomous,
                "gyro": _gyro_rate() is not None}


# ── geometry helpers for navigator.py / routes.py ────────────────────────
def to_world(origin: tuple, local: tuple) -> tuple[float, float]:
    """A point given relative to `origin` (x, y, heading) -> world coords."""
    ox, oy, oh = origin
    lx, ly = local
    h = math.radians(oh)
    return ox + lx * math.cos(h) - ly * math.sin(h), oy + lx * math.sin(h) + ly * math.cos(h)


def to_local(origin: tuple, world: tuple) -> tuple[float, float]:
    """A world point -> coords relative to `origin` (x, y, heading)."""
    ox, oy, oh = origin
    dx, dy = world[0] - ox, world[1] - oy
    h = math.radians(oh)
    return dx * math.cos(h) + dy * math.sin(h), -dx * math.sin(h) + dy * math.cos(h)
