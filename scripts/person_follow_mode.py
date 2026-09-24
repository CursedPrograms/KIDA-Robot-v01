# person_follow_mode.py — mode 8: follow a person, with stereo depth
#
# The robot has two front cameras either side of its centreline, the same
# distance out: cam-0 (night vision, LEFT, YOLO on the Hailo) and cam-1
# (IMX500, RIGHT, on-chip detector). A person seen by both is triangulated
# — the same idea as your two eyes — which gives:
#   - their real distance (Z), independent of the ultrasonic, which may be
#     pinging a chair leg rather than them
#   - their bearing from the robot's *centre*, so it points its middle at
#     you rather than whichever camera it's looking through
#
# Stereo here is object-level, not a per-pixel depth map: the two cameras
# are different sensors/lenses and aren't frame-synced, so rectified block
# matching isn't realistic, but "where is the person's box in each view" is
# robust to all of that.
#
# The IMX500 tracks the target (it's always on and costs nothing); cam-0
# YOLO is switched on for the duration of the mode (and back off after,
# if it was off) so the left view has boxes to pair with. When cam-0 has no
# matching person — out of its view, YOLO busy, low light for the model —
# it falls back to mono: IMX500 bearing with a parallax correction for the
# camera sitting right of centre, and the range sensors for distance.
#
# Distance keeping (person distance = stereo Z, else range sensors, else
# box height):
#   closer than BACKOFF_CM → back away slowly
#   closer than FOLLOW_CM  → hold position, just turn to keep facing them
#   further                → drive toward them, easing off as the gap closes
# Something close ahead and nearer than you (within AVOID_CM) → she goes round
# it: looks left and right with the servo-mounted ultrasonic/laser, turns
# toward the side with more room (using odometry's gyro heading), drives
# past, turns back, and picks you up again with the camera (_avoid()).
# Anything on the range sensors closer than the person also caps forward
# speed, so stereo never drives it into an obstacle in between.
# Person lost for LOST_TIMEOUT_S → stop and wait (no blind searching).
#
# sensor_assist doesn't act in this mode (it only overrides KEYBOARD/
# IR_REMOTE), so the ball-switch bump-stop is repeated inline here, the
# same way line_follow_mode.py does.
#
# ⚠️ Untested on the robot — measure CAM_BASELINE_CM and check the FOVs.
# Stereo distance scales directly with the baseline, so if it reads
# consistently long/short against a tape measure, fix the baseline. If it
# turns *away* from you, flip INVERT_STEER (the log also warns if the two
# views disagree about which side is which — "negative disparity").

import math
import threading
import time
import logging

import state
from arduino import (send_command, set_left_motor, set_right_motor,
                     set_driving_lights, set_stopped_lights)
from haptics import closest_cm
from sensor_assist import _parse_int

logger = logging.getLogger(__name__)

LOOP_DELAY      = 0.1
MIN_CONF        = 0.5
LOST_TIMEOUT_S  = 1.0

BACKOFF_CM      = 25
FOLLOW_CM       = 60
APPROACH_CM     = 80     # full approach speed this far beyond FOLLOW_CM
NEAR_BOX_H      = 0.75   # box taller than this fraction of the frame = close enough

TURN_GAIN       = 1.4    # offset (-0.5..0.5 of frame) → turn (-0.7..0.7)
CENTER_DEADBAND = 0.06
MAX_PWM         = 180    # never faster than this, even at speed 255
MIN_PWM         = 90     # below this the motors just stall
INVERT_STEER    = False

# ── Camera geometry (measure yours) ──
CAM_BASELINE_CM = 8.0    # lens-to-lens distance, cam-0 (left) ↔ cam-1 (right)
CAM0_HFOV_DEG   = 62.2   # night-vision cam — Pi v2 NoIR is 62.2, OV5647 boards 54–72
CAM1_HFOV_DEG   = 66.3   # Raspberry Pi AI Camera (IMX500)
CAM_ASPECT      = 3 / 4  # both run 4:3 frames

STEREO_MAX_AGE_S = 0.3   # both views must be at least this fresh to pair
STEREO_MIN_CM    = 15
STEREO_MAX_CM    = 800
MATCH_MAX_H_DIFF = 0.5   # max relative difference in angular box height
DEPTH_SMOOTHING  = 0.5   # EMA weight of each new stereo depth reading

# ── Going round obstacles ──
AVOID_CM         = 45       # something this close ahead (and nearer than the person) → detour
AVOID_MARGIN_CM  = 30       # ...and the person is at least this much further away
AVOID_COOLDOWN_S = 4.0
BOXED_CM         = 35       # both sides closer than this: don't try, just wait
SCAN_LEFT_DEG    = 45       # servo angles for "look left" / "look right" (arduino00's SERVO_LEFT/RIGHT)
SCAN_RIGHT_DEG   = 135
AVOID_TURN_DEG   = 50
AVOID_PASS_CM    = 40
AVOID_PWM        = 150

_stop_event = threading.Event()
_thread: threading.Thread | None = None


def _clearance(us_cm, laser_mm) -> float:
    """How much room there is in one direction (cm); no echo = plenty."""
    vals = []
    if us_cm is not None and us_cm > 0:
        vals.append(us_cm)
    if laser_mm is not None and laser_mm > 0:
        vals.append(laser_mm / 10.0)
    return min(vals) if vals else 300.0


def _turn_to(target_deg: float, timeout_s: float = 4.0) -> None:
    import odometry
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline and not _stop_event.is_set():
        err = (target_deg - odometry.pose()[2] + 180.0) % 360.0 - 180.0
        if abs(err) < 6:
            break
        t = AVOID_PWM if err > 0 else -AVOID_PWM          # + = turn left (CCW)
        set_left_motor(-t); set_right_motor(t)
        time.sleep(0.05)
    set_left_motor(0); set_right_motor(0)


def _drive_cm(cm: float, timeout_s: float = 4.0) -> None:
    import odometry
    x0, y0, _ = odometry.pose()
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline and not _stop_event.is_set():
        x, y, _ = odometry.pose()
        if math.hypot(x - x0, y - y0) >= cm:
            break
        d = closest_cm()
        if (d is not None and d < 20) or _parse_int(state.ballSwitchValue) == 1:
            break
        set_left_motor(AVOID_PWM); set_right_motor(AVOID_PWM)
        time.sleep(0.05)
    set_left_motor(0); set_right_motor(0)


def _avoid() -> str:
    """Look both ways with the servo-mounted sensor, turn toward the side with
    more room, go past, turn back. Blocking (a few seconds)."""
    import lidar_sweep
    import odometry
    room = {}
    for side, angle in (("left", SCAN_LEFT_DEG), ("right", SCAN_RIGHT_DEG)):
        if _stop_event.is_set():
            return "stopped"
        us, laser = lidar_sweep._read_one_angle(angle)
        room[side] = _clearance(us, laser)
    send_command("dev00", "SERVO:90")
    best = max(room, key=room.get)
    if room[best] < BOXED_CM:
        return f"boxed in (left {room['left']:.0f} cm, right {room['right']:.0f} cm) — waiting"
    start_h = odometry.pose()[2]
    sign = 1 if best == "left" else -1
    _turn_to(start_h + sign * AVOID_TURN_DEG)
    _drive_cm(AVOID_PASS_CM)
    _turn_to(start_h)
    return f"went round it on the {best} ({room[best]:.0f} cm of room)"


# ── geometry helpers ─────────────────────────────────────────────────────
def _tan_half(hfov_deg: float) -> float:
    return math.tan(math.radians(hfov_deg) / 2)


def _bearing_tan(cx: float, hfov_deg: float) -> float:
    """Normalized box centre → tan(horizontal angle), + = robot's right."""
    t = (cx - 0.5) * 2 * _tan_half(hfov_deg)
    return -t if INVERT_STEER else t


def _height_tan(box, hfov_deg: float) -> float:
    """Box height as an angle-independent size, so the two cameras' boxes
    compare even though their lenses differ."""
    return (box[3] - box[1]) * 2 * _tan_half(hfov_deg) * CAM_ASPECT


def _people(boxes) -> list:
    return [d for d in boxes
            if d["label"].lower() == "person" and d["conf"] >= MIN_CONF]


def _pick_target(prev_cx: float | None) -> dict | None:
    people = _people(state.cam1_detection_boxes)
    if not people:
        return None

    def area(d):
        x1, y1, x2, y2 = d["box"]
        return (x2 - x1) * (y2 - y1)

    if prev_cx is None:
        return max(people, key=area)
    # Stick with whoever we were following rather than jumping to a bigger
    # box that just walked into frame.
    return min(people, key=lambda d: abs((d["box"][0] + d["box"][2]) / 2 - prev_cx))


_neg_disparity_warned = False


def _stereo(target: dict) -> tuple[float, float] | None:
    """Pair the IMX500 target with a cam-0 person → (Z cm, bearing tan
    from the robot's centre), or None if there's no usable match."""
    global _neg_disparity_warned
    now = time.monotonic()
    if (now - state.detection_boxes_ts > STEREO_MAX_AGE_S
            or now - state.cam1_detection_boxes_ts > STEREO_MAX_AGE_S):
        return None

    r_box = target["box"]
    t_right = _bearing_tan((r_box[0] + r_box[2]) / 2, CAM1_HFOV_DEG)
    h_right = _height_tan(r_box, CAM1_HFOV_DEG)

    best, best_score, saw_negative = None, None, False
    for cand in _people(state.detection_boxes):
        l_box = cand["box"]
        t_left = _bearing_tan((l_box[0] + l_box[2]) / 2, CAM0_HFOV_DEG)
        # Left camera sees everything further right than the right camera
        # does: tan_L - tan_R = baseline / Z, so it must be positive.
        disparity = t_left - t_right
        if disparity <= 0:
            saw_negative = True
            continue
        z = CAM_BASELINE_CM / disparity
        if not STEREO_MIN_CM <= z <= STEREO_MAX_CM:
            continue
        h_left = _height_tan(l_box, CAM0_HFOV_DEG)
        h_diff = abs(h_left - h_right) / max(h_left, h_right, 1e-6)
        if h_diff > MATCH_MAX_H_DIFF:
            continue
        if best_score is None or h_diff < best_score:
            best, best_score = (z, (t_left + t_right) / 2), h_diff

    if best is None and saw_negative and not _neg_disparity_warned:
        _neg_disparity_warned = True
        logger.warning("Stereo: negative disparity — cam-0/cam-1 disagree on "
                       "left/right; check INVERT_STEER and which cam is which")
        print("⚠️  Person follow: stereo disparity negative — check INVERT_STEER")
    return best


def _mono_bearing_tan(target: dict, dist: int | None) -> float:
    """IMX500-only fallback: its bearing, corrected for the camera sitting
    CAM_BASELINE_CM/2 right of centre (at the range-sensor distance, or the
    follow distance if nothing reads)."""
    cx = (target["box"][0] + target["box"][2]) / 2
    z = dist if dist is not None else FOLLOW_CM
    return _bearing_tan(cx, CAM1_HFOV_DEG) + (CAM_BASELINE_CM / 2) / max(z, 1)


def _forward(person_cm: float | None, obstacle_cm: int | None, box_h: float) -> float:
    if person_cm is not None:
        if person_cm < BACKOFF_CM:
            fwd = -0.5
        elif person_cm < FOLLOW_CM:
            fwd = 0.0
        else:
            fwd = min(1.0, (person_cm - FOLLOW_CM) / APPROACH_CM)
    elif box_h >= NEAR_BOX_H:   # no distance at all — judge by frame fill
        fwd = 0.0
    else:
        fwd = min(1.0, (NEAR_BOX_H - box_h) / NEAR_BOX_H * 2)

    # Something physically in front (maybe not the person) — never drive into it.
    if obstacle_cm is not None:
        if obstacle_cm < BACKOFF_CM:
            fwd = min(fwd, -0.5)
        elif obstacle_cm < FOLLOW_CM:
            fwd = min(fwd, 0.0)
    return fwd


def _to_pwm(v: float, top: int) -> int:
    if abs(v) < 0.02:
        return 0
    mag = MIN_PWM + (top - MIN_PWM) * min(1.0, abs(v))
    return int(mag if v > 0 else -mag)


# ── control loop ─────────────────────────────────────────────────────────
def _run():
    logger.info("Person-follow thread started")
    state.systemStatus = "Follow: searching"
    send_command("dev00", "SERVO:90")   # point US1 straight ahead

    import web_bridge
    yolo_was_on = bool(getattr(state, "inference_on", False))
    if not web_bridge.set_inference(True):
        print("🚶 Person follow: no cam-0 inference available — mono (IMX500 only)")

    prev_cx   = None
    last_avoid = 0.0
    last_seen = 0.0
    sent      = None
    depth_cm  = None     # smoothed stereo depth

    while not _stop_event.is_set():
        try:
            if _parse_int(state.ballSwitchValue) == 1:
                cmd, status = (0, 0), "Follow: ⚠ bump — stopped"
            else:
                target = _pick_target(prev_cx)
                now = time.monotonic()
                if target is not None:
                    last_seen = now
                    x1, y1, x2, y2 = target["box"]
                    prev_cx = (x1 + x2) / 2
                    obstacle = closest_cm()

                    stereo = _stereo(target)
                    if stereo is not None:
                        z, bearing_t = stereo
                        depth_cm = z if depth_cm is None else (
                            depth_cm + DEPTH_SMOOTHING * (z - depth_cm))
                        person_cm, how = depth_cm, "stereo"
                    else:
                        depth_cm = None
                        person_cm, how = obstacle, "mono"
                        bearing_t = _mono_bearing_tan(target, obstacle)

                    # Bearing → the same -0.5..0.5 "fraction of frame" scale
                    # the gains were written for.
                    offset = math.degrees(math.atan(bearing_t)) / CAM1_HFOV_DEG
                    turn = 0.0 if abs(offset) < CENTER_DEADBAND else offset * TURN_GAIN
                    fwd = _forward(person_cm, obstacle, y2 - y1)

                    # Something between her and you? Go round it instead of
                    # just stopping (the range sensors see it, the person is
                    # further off - or she can't tell how far, but it's close).
                    if (obstacle is not None and obstacle < AVOID_CM
                            and (person_cm is None or person_cm > obstacle + AVOID_MARGIN_CM)
                            and time.monotonic() - last_avoid > AVOID_COOLDOWN_S):
                        set_left_motor(0); set_right_motor(0)
                        sent = (0, 0)
                        state.systemStatus = "Follow: something's in the way — looking for a way round"
                        result = _avoid()
                        last_avoid = time.monotonic()
                        last_seen = time.monotonic()      # give the camera a moment to find you again
                        state.systemStatus = f"Follow: {result}"
                        continue

                    left, right = fwd + turn, fwd - turn
                    scale = max(1.0, abs(left), abs(right))
                    speed = state.motorSpeedValue if isinstance(state.motorSpeedValue, int) else MAX_PWM
                    top = max(MIN_PWM, min(MAX_PWM, speed))
                    cmd = (_to_pwm(left / scale, top), _to_pwm(right / scale, top))
                    dist_txt = f"{person_cm:.0f}cm" if person_cm is not None else "?cm"
                    status = (f"Follow[{how}]: {dist_txt} "
                              f"{math.degrees(math.atan(bearing_t)):+.0f}° "
                              f"L{cmd[0]} R{cmd[1]}")
                elif now - last_seen > LOST_TIMEOUT_S:
                    prev_cx, depth_cm = None, None
                    cmd, status = (0, 0), "Follow: searching"
                else:
                    cmd, status = sent or (0, 0), state.systemStatus  # brief dropout — carry on

            if cmd != sent:
                set_left_motor(cmd[0])
                set_right_motor(cmd[1])
                if any(cmd) and not (sent and any(sent)):
                    set_driving_lights()
                elif not any(cmd) and sent and any(sent):
                    set_stopped_lights()
                sent = cmd
            state.systemStatus = status
        except Exception as e:
            logger.error("Person-follow step error: %s", e)
            send_command("dev00", "STOP")
            sent = (0, 0)
        time.sleep(LOOP_DELAY)

    send_command("dev00", "STOP")
    set_stopped_lights()
    if not yolo_was_on:
        web_bridge.set_inference(False)
    state.systemStatus = "Follow: OFF"
    logger.info("Person-follow thread stopped")


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_run, daemon=True, name="PersonFollow")
    _thread.start()
    print("🚶 Person-follow mode started")


def stop() -> None:
    _stop_event.set()
    if _thread:
        _thread.join(timeout=2.0)
    print("🚶 Person-follow mode stopped")
