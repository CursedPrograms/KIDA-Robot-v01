# buttons.py — button definitions for the remote controller, wired to
# RemoteClient.send_action() POSTs instead of local hardware calls.
#
# The Button widget itself lives in button_widget.py, shared with the
# robot's buttons.py, so the two panels always look identical.

from button_widget import Button


def create_buttons(remote) -> list:
    """remote: a RemoteClient instance (see remote_client.py)."""
    pink   = (255, 182, 193)
    blue   = (160, 200, 255)
    purple = (200, 160, 255)
    red    = (255, 140, 140)

    return [
        # Camera / capture
        Button((0, 0, 160, 36), pink,   "Take Photo",     lambda: remote.send_action("photo")),
        Button((0, 0, 160, 36), blue,   "Cam: 0",         lambda: remote.send_action("camera_switch")),
        Button((0, 0, 160, 36), pink,   "Save Inference", lambda: remote.send_action("save_inference")),
        Button((0, 0, 160, 36), pink,   "Record Video",   lambda: remote.send_action("video_start")),
        # Drive modes
        Button((0, 0, 160, 36), blue,   "Keyboard Mode",  lambda: remote.send_action("mode_1")),
        Button((0, 0, 160, 36), blue,   "Autonomous",     lambda: remote.send_action("mode_3")),
        Button((0, 0, 160, 36), purple, "Line Follow",    lambda: remote.send_action("mode_5")),
        Button((0, 0, 160, 36), blue,   "Idle / Stop",    lambda: remote.send_action("mode_4")),
        Button((0, 0, 160, 36), red,    "Watchdog",       lambda: remote.send_action("mode_6")),
        Button((0, 0, 160, 36), purple, "Follow Person",  lambda: remote.send_action("mode_8")),
        # Music
        Button((0, 0, 160, 36), pink,   "Play Music",     lambda: remote.send_action("music_play")),
        Button((0, 0, 160, 36), pink,   "Next Track",     lambda: remote.send_action("music_skip")),
        Button((0, 0, 160, 36), pink,   "Stop Music",     lambda: remote.send_action("music_stop")),
        # LEDs
        Button((0, 0, 160, 36), pink,   "Toggle LEDs",    lambda: remote.send_action("leds_toggle")),
        # Getting around by herself (odometry / navigator)
        Button((0, 0, 160, 36), blue,   "Go Home",        lambda: remote.send_action("go_home")),
    ]
