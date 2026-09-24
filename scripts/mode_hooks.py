# mode_hooks.py — universal side-effects on every drive-mode change
#
# Called by mode_control._on_mode_changed() after every switch.
#
# ⚠️  AUTONOMOUS special case:
#     We must NOT send "STOP" when entering AUTONOMOUS — the Arduino
#     will start its own obstacleAvoidance() loop immediately after
#     receiving AUTO_ON (sent by mode_control.py).  Sending STOP
#     here would race against that and kill the first move.

import state
from leds import toggle_leds, run_chase_effect
from arduino import send_command, set_stopped_lights
from state import DriveMode


def universal_mode_change(new_mode: DriveMode) -> None:
    """
    Runs automatically whenever the drive mode changes.
    Handles motors, LEDs, music, and other global state.
    """
    print(f"🔁 Mode hook → {new_mode.value}")

    # ── Safety: stop motors on every transition EXCEPT into AUTONOMOUS ──
    # (AUTONOMOUS stop is handled by the Arduino's own obstacleAvoidance loop;
    #  sending STOP here would fight the AUTO_ON command sent by mode_control.)
    if new_mode not in (DriveMode.AUTONOMOUS, DriveMode.LINE_FOLLOWER,
                        DriveMode.WATCHDOG, DriveMode.LANE_DETECT,
                        DriveMode.PERSON_FOLLOW):
        try:
            send_command("dev00", "STOP")
            set_stopped_lights()
        except Exception as e:
            print(f"⚠️ mode hook motor/light error: {e}")

    # ── Mode-specific behaviour ──
    if new_mode == DriveMode.WATCHDOG:
        print("🚨 Watchdog mode active — watching for intruders")

    elif new_mode == DriveMode.LINE_FOLLOWER:
        print("〰 Line follower mode active")

    elif new_mode == DriveMode.LANE_DETECT:
        print("🛣️  Lane detect mode active")

    elif new_mode == DriveMode.PERSON_FOLLOW:
        print("🚶 Person follow mode active")

    elif new_mode == DriveMode.KEYBOARD:
        print("🔑 Keyboard mode active")
        toggle_leds()

    elif new_mode == DriveMode.IR_REMOTE:
        print("🎮 IR Remote mode active")

    elif new_mode == DriveMode.AUTONOMOUS:
        print("🤖 Autonomous mode active — Arduino taking control")

    elif new_mode == DriveMode.IDLE:
        print("💤 Idle mode — motors stopped")
        try:
            import web_bridge
            web_bridge.action("music_stop")
        except Exception:
            pass
        run_chase_effect()
