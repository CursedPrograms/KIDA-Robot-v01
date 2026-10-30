# event_handler.py — remote-controller keyboard/mouse dispatch
#
# Mirrors the key bindings in scripts/event_handler.py, but every action
# is a RemoteClient.send_action() POST to the robot's /action route
# instead of a direct hardware call — nothing here touches GPIO, serial,
# or Picamera2.

import threading
import time

import pygame
import drive_mix        # scripts/drive_mix.py — same WASD/curve rule as the robot's own keyboard
import mode_manager
import state

HEARTBEAT_S = 0.3       # the robot auto-stops a held drive it hasn't heard about for ~0.8 s
_last_beat = 0.0

_WASD = (pygame.K_w, pygame.K_s, pygame.K_a, pygame.K_d)
_QAWS_CMD = {pygame.K_q: "left_forward", pygame.K_a: "left_backward",
             pygame.K_w: "right_forward", pygame.K_s: "right_backward"}


def _send(remote, command, **fields):
    """Fire-and-forget, so a slow robot never stalls the HUD."""
    threading.Thread(target=remote.send_action, args=(command,), kwargs=fields, daemon=True).start()


def _drive_commands(pressed_keys) -> list:
    """What the held drive keys mean right now, as [(command, fields)]."""
    if state.drive_scheme == "QAWS":
        out = []
        for side, keys in (("left", (pygame.K_q, pygame.K_a)), ("right", (pygame.K_w, pygame.K_s))):
            held = [k for k in keys if k in pressed_keys]
            out.append((_QAWS_CMD[held[-1]], {}) if held else (f"{side}_stop", {}))
        return out
    intent = drive_mix.wasd_intent(*(k in pressed_keys for k in _WASD))
    if intent[0] == "curve":
        return [("move_curve", {"throttle": intent[1], "turn": intent[2]})]
    if intent[0] == "dir":
        return [({"FORWARD": "move_forward", "BACKWARD": "move_backward",
                  "LEFT": "move_left", "RIGHT": "move_right"}[intent[1]], {})]
    return [("move_stop", {})]


def _drive_now(pressed_keys, remote) -> None:
    global _last_beat
    _last_beat = time.monotonic()
    for command, fields in _drive_commands(pressed_keys):
        _send(remote, command, **fields)


def drive_heartbeat(pressed_keys, remote) -> None:
    """Call every frame: while drive keys are held, resend them, or the
    robot's dead-man timeout stops her mid-hold."""
    if pressed_keys and time.monotonic() - _last_beat >= HEARTBEAT_S:
        _drive_now(pressed_keys, remote)


# mode_N -> the name /status reports once she's in it
MODE_NAMES = {1: "KEYBOARD", 2: "IR_REMOTE", 3: "AUTONOMOUS", 4: "IDLE", 5: "LINE_FOLLOWER",
              6: "WATCHDOG", 7: "LANE_DETECT", 8: "PERSON_FOLLOW", 9: "MIND"}


def handle_events(events, buttons: list, pressed_keys: set, remote,
                  lock_prompt=None, chat_prompt=None, want=None, stop_anywhere=None) -> dict:
    """lock_prompt is main.py's PasswordPrompt, so the 'U' key can open the
    same on-screen prompt the "Lock Motors" button uses (optional; 'U' is a
    no-op without it).
    want(key, value, command): main.py's settings that stick (sent again until her /status
    says key == value); without it the command goes once. stop_anywhere: Backspace."""
    signals = {"quit": False}
    if want is None:
        def want(key, value, command):
            remote.send_action(command)

    for event in events:

        if event.type == pygame.QUIT:
            signals["quit"] = True
            continue

        # ── Keyboard ─────────────────────────────────────────────────────
        if event.type == pygame.KEYDOWN:
            k = event.key

            if pygame.K_1 <= k <= pygame.K_9:   # 9: MIND
                n = k - pygame.K_0
                want("mode", MODE_NAMES[n], f"mode_{n}")
            elif k == pygame.K_BACKSPACE and stop_anywhere is not None:
                stop_anywhere()

            # Quit — Q and ESC both just close this window. There's no
            # run.sh restart loop on this side to distinguish them; that
            # split (see scripts/event_handler.py) is robot-specific.
            # In the QAWS scheme Q is the left track's forward, so only ESC quits.
            elif k == pygame.K_ESCAPE or (k == pygame.K_q and state.drive_scheme != "QAWS"):
                signals["quit"] = True

            elif k == pygame.K_i:
                remote.send_action("inference_toggle")

            elif k == pygame.K_x:
                remote.send_action("speed_cycle")

            elif k == pygame.K_SPACE:
                remote.send_action("hard_stop")

            elif k == pygame.K_m:
                if remote.status.get("music_on"):
                    remote.send_action("music_skip")
                else:
                    want("music_on", True, "music_play")

            elif k == pygame.K_l:
                remote.send_action("leds_toggle")
            elif k == pygame.K_k:
                remote.send_action("leds_effects_toggle")

            # Motor lock — mirrors the "Lock Motors" button: locking is
            # instant, unlocking opens the password prompt (checked
            # server-side, never locally).
            elif k == pygame.K_u:
                if state.motor_lock:
                    if lock_prompt is not None:
                        lock_prompt.open(lambda pw: remote.send_action("motor_lock_off", password=pw))
                else:
                    remote.send_action("motor_lock_on")

            elif k == pygame.K_t and chat_prompt is not None:   # type to her
                chat_prompt.open(lambda text: remote.send_action("chat", text=text))
            elif k == pygame.K_h:
                remote.send_action("go_home")
            elif k == pygame.K_j:
                remote.send_action("hello")
            elif k == pygame.K_n:
                remote.send_action("dance")
            elif k == pygame.K_c:
                remote.send_action("photo")
            elif k == pygame.K_v:
                remote.send_action("video_start")

            # Drive scheme toggle — ,/< = WASD (differential), ./> = QAWS
            # (tank, independent per-motor). Mirrors scripts/event_handler.py.
            elif event.unicode in ('<', ','):
                want("drive_scheme", "WASD", "scheme_wasd")
            elif event.unicode in ('>', '.'):
                want("drive_scheme", "QAWS", "scheme_qaws")

            # Movement — KEYBOARD mode only, mirroring the robot's own guard.
            # Which keys do what depends on state.drive_scheme (synced from
            # /status by remote_client.py).
            # In any mode: driving takes over (back to KEYBOARD, you drive). Her /action only
            # drives in KEYBOARD, so the held keys' heartbeat moves her once she's switched.
            elif ((state.drive_scheme == "QAWS" and k in _QAWS_CMD)
                  or (state.drive_scheme == "WASD" and k in _WASD)):
                if not mode_manager.is_keyboard():
                    print(f"Driving takes over: {state.drive_mode.name} -> KEYBOARD")
                    want("mode", "KEYBOARD", "mode_1")
                pressed_keys.add(k)
                _drive_now(pressed_keys, remote)   # W+A curves (see drive_mix.py)

        elif event.type == pygame.KEYUP:
            if event.key in pressed_keys:
                pressed_keys.discard(event.key)
                _drive_now(pressed_keys, remote)   # release W from W+A: keeps turning

        # ── Mouse ────────────────────────────────────────────────────────
        elif event.type == pygame.MOUSEBUTTONDOWN:
            pos = pygame.mouse.get_pos()
            for button in buttons:
                if button.is_clicked(pos):
                    button.action()

    return signals
