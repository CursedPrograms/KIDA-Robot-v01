# joystick_drive.py — drive KIDA from a USB joystick / gamepad
#
# Shared by both pygame HUDs, so whichever machine the pad is plugged into
# is the one that reads it:
#   - plugged into the Pi  → ui.py uses LocalActions (calls web_bridge.action
#                            in-process, no network)
#   - plugged into the PC  → controller/main.py passes its RemoteClient,
#                            which POSTs to the robot's /action
#   (the website reads a pad plugged into the browser's PC itself — see
#    static/js/main.js, same mapping)
#
# Either way the stick is arcade-mixed here and sent as 'joy_drive' with
# per-side throttle (scripts/web_bridge.py), which scales it by the current
# speed setting and only obeys it in KEYBOARD mode.
#
# Works with the "Generic USB Joystick" from ARM-Robot-v01 and with a
# Logitech wireless gamepad (F710 etc.). On the Logitech, keep the switch
# on the back at X (XInput): A/B/X/Y are then buttons 0-3 on Linux, Windows
# and in browsers alike. D (DirectInput) mode reorders the face buttons;
# that's detected by name and remapped (D_MODE_BUTTON_ACTIONS).
#
# Sends happen on a background thread so a slow robot never stalls the
# HUD's render loop. While the stick is deflected the value is resent every
# HEARTBEAT_S, because the robot auto-stops if it hears nothing for ~800ms
# (web_bridge.check_web_drive_timeout) — so a dropped connection, a dead
# pad battery or a crashed HUD can't leave it driving.

import threading
import time

import pygame

# ---- Joystick wiring ----
AXIS_TURN     = 0      # left stick X: -1 left .. +1 right
AXIS_THROTTLE = 1      # left stick Y: -1 forward .. +1 back (pygame convention)
DEADZONE      = 0.08

# Generic joystick: trigger/B1/B2/B3. Logitech (X mode) / Xbox layout: A/B/X/Y.
BUTTON_ACTIONS = {
    0: "photo",        # trigger | A
    1: "hard_stop",    # B1      | B
    2: "speed_down",   # B2      | X
    3: "speed_up",     # B3      | Y
}

# Logitech pads in D mode report as "... Cordless RumblePad 2" with the
# face buttons ordered X, A, B, Y — remapped so A/B/X/Y do the same thing.
D_MODE_NAMES = ("rumblepad",)
D_MODE_BUTTON_ACTIONS = {
    1: "photo",        # A
    2: "hard_stop",    # B
    0: "speed_down",   # X
    3: "speed_up",     # Y
}

SEND_INTERVAL_S = 0.05
HEARTBEAT_S     = 0.25


def _dz(value: float) -> float:
    return 0.0 if abs(value) < DEADZONE else value


def arcade_mix(turn: float, throttle: float) -> tuple[float, float]:
    """Stick X/Y -> (left, right) track throttle in [-1, 1]."""
    fwd, turn = -_dz(throttle), _dz(turn)
    left, right = fwd + turn, fwd - turn
    scale = max(1.0, abs(left), abs(right))
    return round(left / scale, 2), round(right / scale, 2)


class LocalActions:
    """Same send_action() interface as controller's RemoteClient, but for a
    pad plugged into the Pi: runs the action in-process via web_bridge, so
    the local stick gets identical scaling, lights and dead-man timeout."""

    def send_action(self, command: str, **fields) -> bool:
        import web_bridge
        try:
            web_bridge.action(command, **fields)
            return True
        except Exception as e:
            print(f"⚠️ Joystick action {command}: {e}")
            return False


class JoystickDrive:
    def __init__(self, remote, device: int = 0):
        self.remote   = remote
        self.device   = device
        self.js       = None
        self.buttons  = BUTTON_ACTIONS
        self._target  = (0.0, 0.0)
        self._lock    = threading.Lock()
        self._running = True
        self._open()
        threading.Thread(target=self._sender, daemon=True).start()

    @property
    def name(self) -> str | None:
        return self.js.get_name() if self.js else None

    def _open(self) -> None:
        if self.js is None and pygame.joystick.get_count() > self.device:
            self.js = pygame.joystick.Joystick(self.device)
            self.js.init()
            name = self.js.get_name()
            d_mode = any(n in name.lower() for n in D_MODE_NAMES)
            self.buttons = D_MODE_BUTTON_ACTIONS if d_mode else BUTTON_ACTIONS
            print(f"🕹️  Joystick: {name} (axes={self.js.get_numaxes()}, "
                  f"buttons={self.js.get_numbuttons()}{', D-mode layout' if d_mode else ''})")

    def _set_target(self, left: float, right: float) -> None:
        with self._lock:
            self._target = (left, right)

    def handle_events(self, events) -> None:
        """Call once per frame with that frame's pygame events."""
        for event in events:
            if event.type == pygame.JOYDEVICEADDED:
                self._open()
            elif event.type == pygame.JOYDEVICEREMOVED:
                if self.js is not None and event.instance_id == self.js.get_instance_id():
                    print("🕹️  Joystick disconnected — stopping")
                    self.js = None
                    self._set_target(0.0, 0.0)
            elif event.type == pygame.JOYBUTTONDOWN and self.js is not None:
                cmd = self.buttons.get(event.button)
                if cmd:
                    threading.Thread(target=self.remote.send_action, args=(cmd,),
                                     daemon=True).start()

        if self.js is not None and self.js.get_numaxes() > AXIS_THROTTLE:
            self._set_target(*arcade_mix(self.js.get_axis(AXIS_TURN),
                                         self.js.get_axis(AXIS_THROTTLE)))

    def _sender(self) -> None:
        sent, last = (0.0, 0.0), 0.0
        while self._running:
            with self._lock:
                target = self._target
            now = time.monotonic()
            if target != sent or (any(target) and now - last >= HEARTBEAT_S):
                if self.remote.send_action("joy_drive", left=target[0], right=target[1]):
                    sent, last = target, now
            time.sleep(SEND_INTERVAL_S)

    def stop(self) -> None:
        """Stop the sender and make sure the robot isn't left moving."""
        self._running = False
        with self._lock:
            moving = any(self._target)
        if moving:
            self.remote.send_action("joy_drive", left=0.0, right=0.0)
