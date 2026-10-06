"""
fleet_guard.py - KIDA-01 making way for the other robots.

In Autonomous mode her Arduino (dev00) drives itself; the Pi only switched it
on (AUTO_ON). So when fleet_near.py says another robot is close and has right
of way, this steps in for a moment: AUTO_OFF + STOP while she waits, LEFT to
turn away, then AUTO_ON to hand the wheel back. While a robot is merely near
(or coming closer) she drives at 60 % of the speed you set, then gets it back.

It also tells the others what she's doing (driving / user / parked), in every
mode, about four times a second.

    import fleet_guard; fleet_guard.start(near)      (main.py, after the server)
"""

import threading
import time

import state
from arduino import send_command
from state import DriveMode

SELF_DRIVING = tuple(m for m in (getattr(DriveMode, n, None) for n in
                     ("AUTONOMOUS", "LINE_FOLLOWER", "LANE_DETECT", "PERSON_FOLLOW")) if m is not None)
CAUTION_SCALE = 0.6
STEP_S = 0.25


def _user_speed():
    v = state.motorSpeedValue
    return v if isinstance(v, int) else 255     # arduino.set_motor_speed keeps the last speed you chose


def _run(near):
    phase, slowed = "go", False
    while True:
        mode = getattr(state, "drive_mode", None)
        near.set_state("driving" if mode in SELF_DRIVING else "parked" if mode == DriveMode.IDLE else "user")
        if mode == DriveMode.AUTONOMOUS:
            way = near.give_way(can_turn=True)
            if way != phase:                          # only act on changes: the Arduino keeps doing the last thing
                if way == "wait":
                    send_command("dev00", "AUTO_OFF")
                    send_command("dev00", "STOP")
                elif way == "turn":
                    send_command("dev00", "LEFT")
                else:
                    send_command("dev00", "AUTO_ON")  # back to her own autopilot
                phase = way
            careful = way == "go" and near.advice() == "caution"
            if careful != slowed:
                send_command("dev00", f"SPEED:{int(_user_speed() * (CAUTION_SCALE if careful else 1.0))}")
                slowed = careful
        else:
            if phase != "go" or slowed:               # left Autonomous mid-yield: give her speed back
                send_command("dev00", f"SPEED:{_user_speed()}")
            phase, slowed = "go", False
        time.sleep(STEP_S)


def start(near):
    threading.Thread(target=_run, args=(near,), daemon=True, name="fleet-guard").start()
