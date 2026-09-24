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
# Layout (KEYBOARD mode for driving/servo; buttons work in any mode):
#   left stick   drive (arcade mix → 'joy_drive' per-side throttle)  [WASD scheme]
#   LT / RT      left / right track, analog — squeeze harder, go faster;
#                hold LB / RB to run that track backwards             [tank (QAWS) scheme]
#   right stick  aim the servo-mounted ultrasonic/laser left/right
#   A  photo           B  stop            X  speed −     Y  speed +
#   D-pad ← / →  previous / next drive mode — applied once you stop
#                pressing for MODE_COMMIT_S, so flicking past AUTONOMOUS
#                on the way to another mode never sets it driving
#                (LB / RB do this too in the WASD scheme)
#   D-pad ↑      start / stop video (RT too, in the WASD scheme)
#   Start        lock motors / open the unlock password prompt
#   Back         LIDAR sweep
# The scheme is the same flag the keyboard uses (state.drive_scheme — the
# Scheme button, or < / > keys).
#
# Pads SDL knows the layout of (Logitech F710 in either X or D mode, Xbox,
# PlayStation, …) are read through SDL's GameController API, so the names
# above mean the same buttons on the Pi, on Windows and in the browser.
# The "Generic USB Joystick" from ARM-Robot-v01 is read raw instead
# (RAW_NAMES): SDL does have a mapping for its chip, but for a different
# pad, which would move the trigger off 'photo'. Raw pads get the stick +
# the four face-button actions only (trigger/B1/B2/B3 = A/B/X/Y).
#
# Rumble: the robot decides how hard (haptics.py — tipping, vibration,
# obstacle while driving); the sink's rumble_level() fetches it and the pad
# plays it.
#
# Sends happen on a background thread so a slow robot never stalls the
# HUD's render loop. While the stick is deflected the value is resent every
# HEARTBEAT_S, because the robot auto-stops if it hears nothing for ~800ms
# (web_bridge.check_web_drive_timeout) — so a dropped connection, a dead
# pad battery or a crashed HUD can't leave it driving.

import threading
import time

import pygame

import state

try:
    from pygame._sdl2 import controller as sdl_controller
except ImportError:   # older pygame — everything falls back to raw
    sdl_controller = None

DEADZONE = 0.08

ACTIONS = {
    "a":     "photo",
    "b":     "hard_stop",
    "x":     "speed_down",
    "y":     "speed_up",
    "back":  "lidar_sweep",
}

# Raw (unmapped) pads: button index → logical name.
RAW_NAMES = ("generic usb joystick",)
RAW_BUTTONS = {0: "a", 1: "b", 2: "x", 3: "y"}          # trigger, B1, B2, B3
# Logitech in D mode ("… Cordless RumblePad 2") if SDL has no mapping for it.
D_MODE_NAMES = ("rumblepad",)
D_MODE_BUTTONS = {1: "a", 2: "b", 0: "x", 3: "y"}

TRIGGER_DEADZONE = 0.05
MODE_CYCLE    = [1, 2, 3, 4, 5, 6, 7, 8]   # mode_manager.set_mode_by_number order
MODE_COMMIT_S = 0.8
TRIGGER_ON, TRIGGER_OFF = 0.6, 0.3         # RT hysteresis

SERVO_CENTER    = 90
SERVO_RANGE     = 70    # ± degrees at full right-stick deflection (20..160)
SERVO_STEP      = 5     # only resend once the aim moves this much
SERVO_INTERVAL  = 0.2   # the firmware blocks ~150ms per SERVO: command

SEND_INTERVAL_S = 0.05
HEARTBEAT_S     = 0.25
RUMBLE_POLL_S   = 0.25
RUMBLE_MS       = 400   # a bit longer than the poll, so it's continuous


def _dz(value: float) -> float:
    return 0.0 if abs(value) < DEADZONE else value


def arcade_mix(turn: float, throttle: float) -> tuple[float, float]:
    """Stick X/Y -> (left, right) track throttle in [-1, 1]."""
    fwd, turn = -_dz(throttle), _dz(turn)
    left, right = fwd + turn, fwd - turn
    scale = max(1.0, abs(left), abs(right))
    return round(left / scale, 2), round(right / scale, 2)


def tank_triggers(lt: float, rt: float, left_back: bool, right_back: bool) -> tuple[float, float]:
    """Tank scheme: each trigger is its own track's throttle (0..1), and
    holding the bumper on that side runs it backwards."""
    def side(v, back):
        v = 0.0 if v < TRIGGER_DEADZONE else min(1.0, v)
        return round(-v if back else v, 2)
    return side(lt, left_back), side(rt, right_back)


def servo_angle(stick_x: float) -> int:
    deg = SERVO_CENTER + _dz(stick_x) * SERVO_RANGE
    return int(round(deg / SERVO_STEP) * SERVO_STEP)


class LocalActions:
    """Same interface as controller's RemoteClient (send_action +
    rumble_level), but for a pad plugged into the Pi: runs everything
    in-process, so the local stick gets identical scaling, lights and
    dead-man timeout."""

    def send_action(self, command: str, **fields) -> bool:
        import web_bridge
        try:
            return bool(web_bridge.action(command, **fields))
        except Exception as e:
            print(f"⚠️ Joystick action {command}: {e}")
            return False

    def rumble_level(self) -> tuple[float, float]:
        import haptics
        low, high, _ = haptics.level()
        return low, high


class _Pad:
    """One opened device, read either through SDL's GameController layer
    (named buttons) or as a raw joystick (button numbers)."""

    def __init__(self, index: int):
        self.js = pygame.joystick.Joystick(index)
        self.js.init()
        self.name = self.js.get_name()
        self.instance_id = self.js.get_instance_id()
        lname = self.name.lower()

        self.ctrl = None
        if (sdl_controller is not None and not any(n in lname for n in RAW_NAMES)):
            try:
                sdl_controller.init()
                if sdl_controller.is_controller(index):
                    self.ctrl = sdl_controller.Controller(index)
            except Exception:
                self.ctrl = None

        self.raw_buttons = (D_MODE_BUTTONS if any(n in lname for n in D_MODE_NAMES)
                            else RAW_BUTTONS)
        layout = "named" if self.ctrl else (
            "raw, D-mode" if self.raw_buttons is D_MODE_BUTTONS else "raw")
        print(f"🕹️  Joystick: {self.name} ({layout} layout, "
              f"axes={self.js.get_numaxes()}, buttons={self.js.get_numbuttons()})")

    def read(self) -> tuple[dict, set]:
        """→ (axes {lx, ly, rx, rt}, pressed logical button names)."""
        if self.ctrl is not None:
            c = self.ctrl
            ax = lambda a: c.get_axis(a) / 32767.0
            axes = {
                "lx": ax(pygame.CONTROLLER_AXIS_LEFTX),
                "ly": ax(pygame.CONTROLLER_AXIS_LEFTY),
                "rx": ax(pygame.CONTROLLER_AXIS_RIGHTX),
                "lt": max(0.0, ax(pygame.CONTROLLER_AXIS_TRIGGERLEFT)),
                "rt": max(0.0, ax(pygame.CONTROLLER_AXIS_TRIGGERRIGHT)),
            }
            names = {
                "a": pygame.CONTROLLER_BUTTON_A,
                "b": pygame.CONTROLLER_BUTTON_B,
                "x": pygame.CONTROLLER_BUTTON_X,
                "y": pygame.CONTROLLER_BUTTON_Y,
                "lb": pygame.CONTROLLER_BUTTON_LEFTSHOULDER,
                "rb": pygame.CONTROLLER_BUTTON_RIGHTSHOULDER,
                "start": pygame.CONTROLLER_BUTTON_START,
                "back": pygame.CONTROLLER_BUTTON_BACK,
                "dleft": pygame.CONTROLLER_BUTTON_DPAD_LEFT,
                "dright": pygame.CONTROLLER_BUTTON_DPAD_RIGHT,
                "dup": pygame.CONTROLLER_BUTTON_DPAD_UP,
            }
            return axes, {n for n, b in names.items() if c.get_button(b)}

        js = self.js
        axes = {"lx": 0.0, "ly": 0.0, "rx": None, "lt": None, "rt": None}
        if js.get_numaxes() > 1:
            axes["lx"], axes["ly"] = js.get_axis(0), js.get_axis(1)
        pressed = {n for i, n in self.raw_buttons.items()
                   if i < js.get_numbuttons() and js.get_button(i)}
        return axes, pressed

    def rumble(self, low: float, high: float) -> None:
        try:
            if low or high:
                (self.ctrl or self.js).rumble(low, high, RUMBLE_MS)
            else:
                (self.ctrl or self.js).stop_rumble()
        except Exception:
            pass   # pad without rumble motors


class JoystickDrive:
    def __init__(self, remote, on_unlock_request=None, device: int = 0):
        """remote: LocalActions() or controller's RemoteClient.
        on_unlock_request: called (main thread) when Start is pressed while
        the motors are locked — should open that HUD's password prompt."""
        self.remote   = remote
        self.device   = device
        self.on_unlock_request = on_unlock_request
        self.pad: _Pad | None = None

        self._prev_pressed: set = set()
        self._rt_down     = False
        self._pending_mode: int | None = None
        self._pending_ts  = 0.0

        self._target  = (0.0, 0.0)
        self._servo   = SERVO_CENTER
        self._rumble  = (0.0, 0.0)
        self._played_rumble = (0.0, 0.0)
        self._lock    = threading.Lock()
        self._running = True
        self._open(device)
        threading.Thread(target=self._sender, daemon=True).start()

    @property
    def name(self) -> str | None:
        return self.pad.name if self.pad else None

    def _open(self, index: int) -> None:
        if self.pad is None and pygame.joystick.get_count() > index:
            self.pad = _Pad(index)
            self._prev_pressed = set()
            state.joystick_name = self.pad.name

    def _close(self) -> None:
        print("🕹️  Joystick disconnected — stopping")
        self.pad = None
        state.joystick_name = None
        state.joystick_pending_mode = None
        self._pending_mode = None
        with self._lock:
            self._target = (0.0, 0.0)
            self._servo = SERVO_CENTER

    def _fire(self, command: str) -> None:
        threading.Thread(target=self.remote.send_action, args=(command,),
                         daemon=True).start()

    # ── called from the HUD's main loop ──
    def handle_events(self, events) -> None:
        """Call once per frame with that frame's pygame events."""
        for event in events:
            if event.type == pygame.JOYDEVICEADDED:
                self._open(event.device_index)
            elif event.type == pygame.JOYDEVICEREMOVED:
                if self.pad is not None and event.instance_id == self.pad.instance_id:
                    self._close()

        if self.pad is None:
            return

        axes, pressed = self.pad.read()
        tank = state.drive_scheme == "QAWS" and axes["lt"] is not None
        for name in pressed - self._prev_pressed:
            self._on_press(name, tank)
        self._prev_pressed = pressed

        if axes["rt"] is not None and not tank:   # in tank mode RT is the right track
            if not self._rt_down and axes["rt"] > TRIGGER_ON:
                self._rt_down = True
                self._fire("video_toggle")
            elif self._rt_down and axes["rt"] < TRIGGER_OFF:
                self._rt_down = False

        now = time.monotonic()
        if self._pending_mode is not None and now - self._pending_ts >= MODE_COMMIT_S:
            self._fire(f"mode_{self._pending_mode}")
            self._pending_mode = None
            state.joystick_pending_mode = None

        with self._lock:
            if tank:
                self._target = tank_triggers(axes["lt"], axes["rt"], "lb" in pressed, "rb" in pressed)
            else:
                self._target = arcade_mix(axes["lx"], axes["ly"])
            if axes["rx"] is not None:
                self._servo = servo_angle(axes["rx"])
            if self._rumble != self._played_rumble:
                self.pad.rumble(*self._rumble)
                self._played_rumble = self._rumble

    def _on_press(self, name: str, tank: bool = False) -> None:
        if name in ACTIONS:
            self._fire(ACTIONS[name])
        elif name in ("dleft", "dright"):
            self._step_mode(-1 if name == "dleft" else 1)
        elif name in ("lb", "rb") and not tank:   # in tank mode they reverse a track instead
            self._step_mode(-1 if name == "lb" else 1)
        elif name == "dup":
            self._fire("video_toggle")
        elif name == "start":
            if state.motor_lock:
                if self.on_unlock_request:
                    self.on_unlock_request()
            else:
                self._fire("motor_lock_on")

    def _step_mode(self, step: int) -> None:
        import mode_manager
        from state import DriveMode
        if self._pending_mode is None:
            numbers = {DriveMode.KEYBOARD: 1, DriveMode.IR_REMOTE: 2,
                       DriveMode.AUTONOMOUS: 3, DriveMode.IDLE: 4,
                       DriveMode.LINE_FOLLOWER: 5, DriveMode.WATCHDOG: 6,
                       DriveMode.LANE_DETECT: 7, DriveMode.PERSON_FOLLOW: 8}
            base = numbers.get(mode_manager.current_mode(), 1)
        else:
            base = self._pending_mode
        i = MODE_CYCLE.index(base) if base in MODE_CYCLE else 0
        self._pending_mode = MODE_CYCLE[(i + step) % len(MODE_CYCLE)]
        self._pending_ts = time.monotonic()
        state.joystick_pending_mode = self._pending_mode
        print(f"🕹️  Mode → {self._pending_mode} (applies in {MODE_COMMIT_S}s)")

    # ── background: drive/servo sends + rumble polling ──
    def _sender(self) -> None:
        sent, last = (0.0, 0.0), 0.0
        servo_sent, servo_last = SERVO_CENTER, 0.0
        rumble_last = 0.0
        while self._running:
            with self._lock:
                target, servo = self._target, self._servo
                has_pad = self.pad is not None
            now = time.monotonic()

            if target != sent or (any(target) and now - last >= HEARTBEAT_S):
                if self.remote.send_action("joy_drive", left=target[0], right=target[1]):
                    sent, last = target, now

            # Only in KEYBOARD mode, like driving — the robot refuses it in
            # most other modes anyway, so don't spam it.
            if (servo != servo_sent and now - servo_last >= SERVO_INTERVAL
                    and state.drive_mode.name in ("KEYBOARD", "IDLE")):
                self.remote.send_action("servo_aim", angle=servo)
                servo_sent, servo_last = servo, now

            if has_pad and now - rumble_last >= RUMBLE_POLL_S:
                rumble_last = now
                level = (0.0, 0.0)
                getter = getattr(self.remote, "rumble_level", None)
                if getter:
                    try:
                        level = getter()
                    except Exception:
                        pass
                with self._lock:
                    self._rumble = level
                    if any(level):
                        self._played_rumble = None   # replay: effects time out
            time.sleep(SEND_INTERVAL_S)

    def stop(self) -> None:
        """Stop the sender and make sure the robot isn't left moving."""
        self._running = False
        with self._lock:
            moving = any(self._target)
        if moving:
            self.remote.send_action("joy_drive", left=0.0, right=0.0)
        if self.pad:
            self.pad.rumble(0.0, 0.0)
