# buttons.py — button definitions for KIDA, wired to local hardware
#
# The Button widget itself lives in button_widget.py (shared with
# controller/buttons.py, the remote-controller equivalent of this file) —
# only the action wiring below is robot-specific.

from button_widget import Button
from leds import toggle_leds
from camera_actions import (take_photo, start_video, stop_video,
                            cycle_camera, save_inference_photo)
from arduino import send_command
from mode_control import switch_mode
import wheel_calibration
import lidar_sweep
import sfx


def create_buttons(music_ctrl=None) -> list:
    """
    music_ctrl: MusicPlayer instance from ui.py.
    Pass it here so the Play/Skip/Stop buttons use the live player,
    not the old music.py module globals.
    """
    pink   = (255, 182, 193)
    blue   = (160, 200, 255)
    purple = (200, 160, 255)
    red    = (255, 140, 140)

    def music_play():
        if music_ctrl:
            if music_ctrl.is_playing():
                music_ctrl.skip()
            else:
                music_ctrl.start()

    def music_skip():
        if music_ctrl:
            music_ctrl.skip()

    def music_stop():
        if music_ctrl:
            music_ctrl.stop()

    # Button-triggered capture plays only the sound effect — no spoken
    # reply, since pressing a button isn't a conversation turn (voice
    # commands in voice_commands.py speak first, then play the same effect).
    def photo_btn():
        take_photo()
        sfx.play("camera_shutter.mp3")

    def video_btn():
        start_video()
        sfx.play("video_reel.mp3")

    return [
        # Camera / capture
        Button((0, 0, 160, 36), pink,   "Take Photo",    photo_btn),
        Button((0, 0, 160, 36), blue,   "Cam: 0",        cycle_camera),
        Button((0, 0, 160, 36), pink,   "Save Inference", save_inference_photo),
        Button((0, 0, 160, 36), pink,   "Record Video",  video_btn),
        # Drive modes
        Button((0, 0, 160, 36), blue,   "Keyboard Mode", lambda: switch_mode(1)),
        Button((0, 0, 160, 36), blue,   "Autonomous",    lambda: switch_mode(3)),
        Button((0, 0, 160, 36), purple, "Line Follow",   lambda: switch_mode(5)),
        Button((0, 0, 160, 36), blue,   "Idle / Stop",   lambda: switch_mode(4)),
        Button((0, 0, 160, 36), red,    "Watchdog",      lambda: switch_mode(6)),
        Button((0, 0, 160, 36), purple, "Lane Detect",   lambda: switch_mode(7)),
        # Music
        Button((0, 0, 160, 36), pink,   "Play Music",    music_play),
        Button((0, 0, 160, 36), pink,   "Next Track",    music_skip),
        Button((0, 0, 160, 36), pink,   "Stop Music",    music_stop),
        # LEDs
        Button((0, 0, 160, 36), pink,   "Toggle LEDs",   toggle_leds),
        # Wheel calibration
        Button((0, 0, 160, 36), purple, "Calibrate Wheels", wheel_calibration.run_calibration),
        Button((0, 0, 160, 36), blue,   "Trim -",        lambda: wheel_calibration.nudge_trim(-1)),
        Button((0, 0, 160, 36), blue,   "Trim +",        lambda: wheel_calibration.nudge_trim(1)),
        # Lidar-style sweep
        Button((0, 0, 160, 36), purple, "Lidar Sweep",   lidar_sweep.run_sweep),
    ]
