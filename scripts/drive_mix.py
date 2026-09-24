# drive_mix.py — turn held WASD keys into a drive, including curves
#
# One place for the rule every WASD client follows (the Pi's own keyboard,
# the website, the PC controller, and the C++ controller mirrors it):
#
#   W / S alone      FORWARD / BACKWARD  (the firmware's preset, wheel trim applies)
#   A / D alone      LEFT / RIGHT        (rotate on the spot)
#   W+A, W+D, S+A, S+D                   a curve: both tracks keep turning the
#                                        same way, the inside one slower
#                                        (config.CURVE_INNER_RATIO), so she
#                                        turns *while* moving - neither motor
#                                        stops
#   W+S or A+D cancel out; nothing held = stop.
#
# Curves go out as LMOTOR/RMOTOR (per-track speed), which the firmware
# already supports for the tank scheme.

try:
    import config
    CURVE_INNER_RATIO = getattr(config, "CURVE_INNER_RATIO", 0.35)
except Exception:          # the PC controller doesn't need the robot's config
    CURVE_INNER_RATIO = 0.35


def wasd_intent(forward: bool, backward: bool, left: bool, right: bool):
    """Held keys -> ("stop",) | ("dir", "FORWARD"|"BACKWARD"|"LEFT"|"RIGHT") |
    ("curve", throttle, turn) with throttle/turn in {-1, +1}."""
    throttle = (1 if forward else 0) - (1 if backward else 0)
    turn = (1 if right else 0) - (1 if left else 0)
    if throttle and turn:
        return ("curve", throttle, turn)
    if throttle:
        return ("dir", "FORWARD" if throttle > 0 else "BACKWARD")
    if turn:
        return ("dir", "RIGHT" if turn > 0 else "LEFT")
    return ("stop",)


def curve_speeds(throttle: int, turn: int, speed: int, inner: float = None) -> tuple[int, int]:
    """(left, right) track PWM for a curve at `speed`: the inside track (the
    side you're turning toward) runs at `inner` of the outside one."""
    inner = CURVE_INNER_RATIO if inner is None else inner
    t = 1 if throttle >= 0 else -1
    outer, slow = int(speed), int(round(speed * max(0.0, min(1.0, inner))))
    left, right = (slow, outer) if turn < 0 else (outer, slow)
    return left * t, right * t
