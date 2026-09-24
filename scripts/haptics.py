# haptics.py — how hard the driver's gamepad should rumble right now
#
# Computed on the robot (it owns the sensors) and read by every pad:
#   - Pi pad        → joystick_drive.LocalActions.rumble_level() calls level()
#   - PC controller → /status 'rumble' (RemoteClient polls it every 0.5s)
#   - website       → /haptics (polled only while a gamepad is connected)
#
# Returns (low, high) motor strengths in 0..1 — low = the heavy/rumbly motor,
# high = the light/buzzy one — plus a short reason for the HUD/log.
#
#   Tipping   tilt from the startup "level" pose past TIP_DEG  → both motors full
#   Vibration vibration_guard.py has slowed us down            → heavy motor, medium
#   Obstacle  closest range under sensor_assist's WARN_DIST_CM → light motor,
#             stronger the closer it gets; full at STOP_DIST_CM.
#             Only while being driven by pad/web — a buzzing pad while parked
#             next to a wall would just be noise.

import math

import state
from sensor_assist import _parse_int, STOP_DIST_CM, WARN_DIST_CM

TIP_DEG = 30   # degrees away from the startup pose that counts as tipping

_level_vec = None   # gravity direction at startup, so any MPU mounting works


def _tilt_deg() -> float | None:
    global _level_vec
    if not getattr(state, "mpu_available", False):
        return None
    a = (state.mpu_ax, state.mpu_ay, state.mpu_az)
    norm = math.sqrt(sum(v * v for v in a))
    if norm < 0.3:          # free-fall / garbage read
        return None
    a = tuple(v / norm for v in a)
    if _level_vec is None:
        _level_vec = a
        return 0.0
    dot = max(-1.0, min(1.0, sum(x * y for x, y in zip(a, _level_vec))))
    return math.degrees(math.acos(dot))


def closest_cm() -> int | None:
    """Nearest reading across the laser and both ultrasonics, in cm."""
    dists = [
        v for v in (
            _parse_int(state.laserValue),
            _parse_int(state.ultrasonic0Value),
            _parse_int(state.ultrasonic1Value),
        )
        if v is not None and v > 0
    ]
    return min(dists) if dists else None


def level() -> tuple[float, float, str]:
    tilt = _tilt_deg()
    if tilt is not None and tilt > TIP_DEG:
        return 1.0, 1.0, f"tipping {tilt:.0f}°"

    if getattr(state, "vibration_active", False):
        return 0.6, 0.0, "vibration"

    import web_bridge
    if web_bridge.is_driving():
        closest = closest_cm()
        if closest is not None and closest < WARN_DIST_CM:
            span = max(1, WARN_DIST_CM - STOP_DIST_CM)
            strength = min(1.0, 0.25 + 0.75 * (WARN_DIST_CM - closest) / span)
            return 0.0, round(strength, 2), f"obstacle {closest} cm"

    return 0.0, 0.0, ""
