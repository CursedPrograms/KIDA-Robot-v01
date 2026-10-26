# buttons.py — button definitions for the remote controller, wired to
# RemoteClient.send_action() POSTs instead of local hardware calls.
#
# The Button widget itself lives in button_widget.py, shared with the
# robot's buttons.py, so the two panels always look identical.

from button_widget import Button


def create_buttons(remote, want=None) -> list:
    """remote: a RemoteClient instance (see remote_client.py). want(key, value, command):
    main.py's settings that stick, for the mode buttons (without it they send once)."""
    def mode(n, name):
        if want is None:
            return lambda: remote.send_action(f"mode_{n}")
        return lambda: want("mode", name, f"mode_{n}")

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
        Button((0, 0, 160, 36), blue,   "Keyboard Mode",  mode(1, "KEYBOARD")),
        Button((0, 0, 160, 36), blue,   "Autonomous",     mode(3, "AUTONOMOUS")),
        Button((0, 0, 160, 36), purple, "Line Follow",    mode(5, "LINE_FOLLOWER")),
        Button((0, 0, 160, 36), blue,   "Idle / Stop",    mode(4, "IDLE")),
        Button((0, 0, 160, 36), red,    "Watchdog",       mode(6, "WATCHDOG")),
        Button((0, 0, 160, 36), purple, "Follow Person",  mode(8, "PERSON_FOLLOW")),
        Button((0, 0, 160, 36), purple, "Mind Mode",      mode(9, "MIND")),
        # Music
        Button((0, 0, 160, 36), pink,   "Play Music",
               lambda: remote.send_action("music_play") if want is None else want("music_on", True, "music_play")),
        Button((0, 0, 160, 36), pink,   "Next Track",     lambda: remote.send_action("music_skip")),
        Button((0, 0, 160, 36), pink,   "Stop Music",
               lambda: remote.send_action("music_stop") if want is None else want("music_on", False, "music_stop")),
        # LEDs
        Button((0, 0, 160, 36), pink,   "Toggle LEDs",    lambda: remote.send_action("leds_toggle")),
        # Getting around by herself (odometry / navigator)
        Button((0, 0, 160, 36), blue,   "Go Home",        lambda: remote.send_action("go_home")),
    ]
