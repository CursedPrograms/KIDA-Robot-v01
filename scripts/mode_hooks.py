# mode_hooks.py
import state
from leds import toggle_leds, run_chase_effect
from music import stop_music
from arduino import send_command
from state import DriveMode

def universal_mode_change(new_mode: DriveMode):
    """
    Runs automatically whenever the drive mode changes.
    Handles motors, LEDs, music, and other global updates.
    """
    print(f"🔁 Universal mode hook: switched to {new_mode.value}")

    # Safety: stop all motors and reset lights
    try:
        send_command("dev00", "STOP")                # Main motor Arduino
        send_command("dev01", "LIGHT_FRONT_OFF")    # Front lights
        send_command("dev01", "LIGHT_BACK_ON")      # Back lights (optional)
    except Exception as e:
        print(f"⚠️ universal_mode_change motor/light error: {e}")

    # Mode-specific behavior
    if new_mode == DriveMode.KEYBOARD:
        print("🔑 Keyboard mode active")
        toggle_leds()  # e.g., flash keyboard LED indicators

    elif new_mode == DriveMode.IR_REMOTE:
        print("🎮 IR Remote mode active")
        # Optional: update LEDs or feedback for IR

    elif new_mode == DriveMode.AUTONOMOUS:
        print("🤖 Autonomous mode active")
        # Optional: start AI routines, camera, sensors, etc.

    elif new_mode == DriveMode.IDLE:
        print("💤 Idle mode — motors stopped")
        stop_music()
        run_chase_effect()  # optional idle LED pattern