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
from music import stop_music
from arduino import send_command
from state import DriveMode
import pygame

        #pygame.mixer.pre_init(44100, -16, 2, 1024)
        # pygame.mixer.init()

def universal_mode_change(new_mode: DriveMode) -> None:
    """
    Runs automatically whenever the drive mode changes.
    Handles motors, LEDs, music, and other global state.
    """
    print(f"🔁 Mode hook → {new_mode.value}")

    # ── Safety: stop motors on every transition EXCEPT into AUTONOMOUS ──
    # (AUTONOMOUS stop is handled by the Arduino's own obstacleAvoidance loop;
    #  sending STOP here would fight the AUTO_ON command sent by mode_control.)
    if new_mode != DriveMode.AUTONOMOUS:
        try:
            send_command("dev00", "STOP")
            send_command("dev01", "LIGHT_FRONT_OFF")
            send_command("dev01", "LIGHT_BACK_ON")
        except Exception as e:
            print(f"⚠️ mode hook motor/light error: {e}")

    # ── Mode-specific behaviour ──
    if new_mode == DriveMode.KEYBOARD:
        print("🔑 Keyboard mode active")
        # pygame.mixer.music.load("./audio/keyboard_mode.mp3")
        # pygame.mixer.music.play()
        toggle_leds()

    elif new_mode == DriveMode.IR_REMOTE:
        # pygame.mixer.music.load("./audio/IR_remote_mode.mp3")
        # pygame.mixer.music.play()
        print("🎮 IR Remote mode active")

    elif new_mode == DriveMode.AUTONOMOUS:
        print("🤖 Autonomous mode active — Arduino taking control")
        # pygame.mixer.music.load("./audio/autonomous_mode.mp3")
        # pygame.mixer.music.play()
        # AUTO_ON is sent by mode_control._on_mode_changed() before this runs.
        # Nothing extra needed here; add camera/AI startup hooks if required.

    elif new_mode == DriveMode.IDLE:
        print("💤 Idle mode — motors stopped")
        # pygame.mixer.music.load("./audio/idle_mode.mp3")
        # pygame.mixer.music.play()
        stop_music()
        run_chase_effect()
