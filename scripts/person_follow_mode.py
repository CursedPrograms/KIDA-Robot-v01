# person_follow_mode.py — mode 8: follow a person seen by cam-1
#
# Uses cam-1's IMX500 on-chip detector (state.cam1_detection_boxes, written
# by imx500_cam1.py), so this costs no Pi CPU and never touches the Hailo-8L
# or cam-0's YOLO toggle. Steering is proportional via LMOTOR/RMOTOR (tank
# drive), not the bucketed FORWARD/LEFT/RIGHT the lane/line modes use, so
# the robot curves smoothly toward the person instead of zig-zagging.
#
# Distance keeping uses the real range sensors (laser + both ultrasonics,
# same set sensor_assist watches), with the person's box height as a
# fallback when they read nothing:
#   closer than BACKOFF_CM → back away slowly
#   closer than FOLLOW_CM  → hold position, just turn to keep facing them
#   further                → drive toward them, easing off as the gap closes
# Person lost for LOST_TIMEOUT_S → stop and wait (no blind searching).
#
# sensor_assist doesn't act in this mode (it only overrides KEYBOARD/
# IR_REMOTE), so the ball-switch bump-stop is repeated inline here, the
# same way line_follow_mode.py does.
#
# The IMX500 (cam-1) is mounted on the RIGHT of the robot's front (the
# night-vision cam-0 is on the left), so a person dead ahead of the robot's
# centre shows up left of the IMX500's frame centre — more so the closer
# they are. _parallax() shifts the aim point by that amount (using the real
# range reading), so the robot points its middle at you, not its right side.
#
# ⚠️ Untested on the robot: the gains/distances below are a starting guess.
# If it turns *away* from you, flip INVERT_STEER.

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
FOLLOW_CM       = 50
APPROACH_CM     = 60     # full approach speed this far beyond FOLLOW_CM
NEAR_BOX_H      = 0.75   # box taller than this fraction of the frame = close enough

TURN_GAIN       = 1.4    # offset (-0.5..0.5 of frame) → turn (-0.7..0.7)
CENTER_DEADBAND = 0.06
MAX_PWM         = 180    # never faster than this, even at speed 255
MIN_PWM         = 90     # below this the motors just stall
INVERT_STEER    = False

CAM1_OFFSET_CM  = 4.0    # IMX500 lens → robot centreline, to the right (measure yours)
CAM1_HFOV_DEG   = 66.0   # Raspberry Pi AI Camera horizontal field of view

_stop_event = threading.Event()
_thread: threading.Thread | None = None


def _pick_target(prev_cx: float | None) -> dict | None:
    people = [d for d in state.cam1_detection_boxes
              if d["label"].lower() == "person" and d["conf"] >= MIN_CONF]
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


def _parallax(dist: int | None) -> float:
    """Where (as a steering offset, -0.5..0.5 of the frame) a person
    straight ahead of the robot's centre appears in the IMX500's view:
    left of centre, since the camera sits right of the centreline. Without
    a range reading assume they're at the follow distance."""
    d = dist if dist is not None else FOLLOW_CM
    angle = math.degrees(math.atan2(CAM1_OFFSET_CM, max(d, 1)))
    return -angle / CAM1_HFOV_DEG


def _forward(dist: int | None, box_h: float) -> float:
    if dist is not None:
        if dist < BACKOFF_CM:
            return -0.5
        if dist < FOLLOW_CM:
            return 0.0
        return min(1.0, (dist - FOLLOW_CM) / APPROACH_CM)
    # No range reading — judge by how much of the frame they fill.
    if box_h >= NEAR_BOX_H:
        return 0.0
    return min(1.0, (NEAR_BOX_H - box_h) / NEAR_BOX_H * 2)


def _to_pwm(v: float, top: int) -> int:
    if abs(v) < 0.02:
        return 0
    mag = MIN_PWM + (top - MIN_PWM) * min(1.0, abs(v))
    return int(mag if v > 0 else -mag)


def _run():
    logger.info("Person-follow thread started")
    state.systemStatus = "Follow: searching"
    send_command("dev00", "SERVO:90")   # point US1 straight ahead

    prev_cx   = None
    last_seen = 0.0
    sent      = None

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
                    offset = prev_cx - 0.5
                    if INVERT_STEER:
                        offset = -offset
                    dist = closest_cm()
                    offset -= _parallax(dist)
                    turn = 0.0 if abs(offset) < CENTER_DEADBAND else offset * TURN_GAIN
                    fwd = _forward(dist, y2 - y1)

                    left, right = fwd + turn, fwd - turn
                    scale = max(1.0, abs(left), abs(right))
                    speed = state.motorSpeedValue if isinstance(state.motorSpeedValue, int) else MAX_PWM
                    top = max(MIN_PWM, min(MAX_PWM, speed))
                    cmd = (_to_pwm(left / scale, top), _to_pwm(right / scale, top))
                    status = f"Follow: L{cmd[0]} R{cmd[1]} off={offset:+.2f}"
                elif now - last_seen > LOST_TIMEOUT_S:
                    prev_cx = None
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
