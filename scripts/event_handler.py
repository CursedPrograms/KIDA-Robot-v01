# event_handler.py — keyboard and mouse event dispatch for KIDA
#
# Music is handled directly here via the music_ctrl MusicPlayer instance
# passed in from ui.py, so this module has zero music-module imports.
#
# Returns a signals dict so ui.py stays thin:
#   quit             bool
#   inference_toggle bool
#   motor_speed      int

import pygame
import config
import leds
import mode_manager
import motor_lock
import sfx
import state
import drive_mix

from state import DriveMode
from arduino import (send_command, set_motor_speed, set_driving_lights,
                     set_stopped_lights, set_left_motor, set_right_motor)
from mode_control import switch_mode, switch_mode_direct
from camera_actions import take_photo, start_video


def _apply_wasd(pressed_keys: set, motor_speed: int) -> None:
    """Drive from whichever WASD keys are held now (see drive_mix.py): one key
    is the usual preset direction, a diagonal curves, nothing held stops."""
    intent = drive_mix.wasd_intent(pygame.K_w in pressed_keys, pygame.K_s in pressed_keys,
                                   pygame.K_a in pressed_keys, pygame.K_d in pressed_keys)
    if intent[0] == "curve":
        l, r = drive_mix.curve_speeds(intent[1], intent[2], motor_speed)
        set_left_motor(l)
        set_right_motor(r)
        set_driving_lights()
    elif intent[0] == "dir":
        send_command("dev00", intent[1])
        set_driving_lights()
    else:
        send_command("dev00", "STOP")
        set_stopped_lights()


def _mind_drive() -> None:
    """You're driving: ends any route/go-home she's doing by herself, and tells
    her inner life she's being driven (resets her doze-off timer, wakes her)."""
    _stop_navigating()
    try:
        import kida_mind_host
        kida_mind_host.note_activity("drive")
    except Exception:
        pass


def _stop_navigating() -> None:
    try:
        import navigator
        if navigator.active():
            import routes
            routes.stop()
    except Exception:
        pass


def handle_events(events, buttons: list,
                  pressed_keys: set,
                  motor_speed: int,
                  inference_on: bool,
                  music_ctrl=None,
                  lock_prompt=None) -> dict:
    """
    Process all pending pygame events.
    music_ctrl is the MusicPlayer instance from ui.py (optional; safe to omit).
    lock_prompt is ui.py's PasswordPrompt for motor-lock, so the 'U' key can
    open the same on-screen prompt the "Lock Motors" button uses (optional;
    'U' is a no-op without it).
    """
    signals = {
        "quit":             False,
        "hard_quit":        False,
        "inference_toggle": False,
        "motor_speed":      motor_speed,
    }

    for event in events:

        if event.type == pygame.QUIT:
            signals["quit"] = True
            continue

        # ── Keyboard ─────────────────────────────────────────────────────────
        if event.type == pygame.KEYDOWN:
            k = event.key

            # Mode select — always available regardless of current mode
            if k == pygame.K_1:
                switch_mode(1)
            elif k == pygame.K_2:
                switch_mode(2)
            elif k == pygame.K_3:
                switch_mode(3)
            elif k == pygame.K_4:
                switch_mode(4)
            elif k == pygame.K_5:
                switch_mode(5)
            elif k == pygame.K_6:
                switch_mode(6)
            elif k == pygame.K_7:
                switch_mode(7)
            elif k == pygame.K_8:
                switch_mode(8)

            # Quit — Q kills the process for good; ESC just closes the UI
            # and lets run.sh's restart loop bring it back up.
            elif k == pygame.K_q:
                switch_mode_direct(DriveMode.IDLE)
                signals["quit"]      = True
                signals["hard_quit"] = True
            elif k == pygame.K_ESCAPE:
                switch_mode_direct(DriveMode.IDLE)
                signals["quit"] = True

            # Inference toggle (cam-0 YOLO)
            elif k == pygame.K_i:
                signals["inference_toggle"] = True

            # Speed cycle
            elif k == pygame.K_x:
                signals["motor_speed"] += config.SPEED_STEP
                if signals["motor_speed"] > config.MAX_SPEED:
                    signals["motor_speed"] = config.MIN_SPEED
                set_motor_speed(signals["motor_speed"])
                print(f"⚡ Speed: {signals['motor_speed']}")

            # Hard stop — motors + music
            elif k == pygame.K_SPACE:
                _stop_navigating()
                send_command("dev00", "STOP")
                set_stopped_lights()
                if music_ctrl:
                    music_ctrl.stop()
                print("🛑 STOP")

            # Music — play or skip if already playing
            elif k == pygame.K_m:
                if music_ctrl:
                    if music_ctrl.is_playing():
                        music_ctrl.skip()
                    else:
                        music_ctrl.start()

            # LEDs
            elif k == pygame.K_l:
                leds.toggle_leds()
            elif k == pygame.K_k:
                leds.toggle_effects()

            # Motor lock — mirrors the "Lock Motors" button: locking is
            # instant, unlocking opens the password prompt.
            elif k == pygame.K_u:
                if motor_lock.is_locked():
                    if lock_prompt is not None:
                        lock_prompt.open(lambda pw: motor_lock.try_unlock(pw))
                else:
                    motor_lock.lock()

            # Photo / video capture
            elif k == pygame.K_c:
                take_photo()
                sfx.play("camera_shutter.mp3")
            elif k == pygame.K_v:
                start_video()
                sfx.play("video_reel.mp3")

            # Drive scheme toggle — ,/< = WASD (differential), ./> = QAWS
            # (tank, independent per-motor). Plain comma/period work too,
            # not just the shifted symbols. Shared with the web HUD and
            # the remote controller via state.drive_scheme.
            elif event.unicode in ('<', ','):
                state.drive_scheme = "WASD"
                print("⌨️ Drive scheme: WASD")
            elif event.unicode in ('>', '.'):
                state.drive_scheme = "QAWS"
                print("⌨️ Drive scheme: QAWS (Q/A=left motor, W/S=right motor)")

            # Movement — KEYBOARD mode only. Which keys do what depends on
            # state.drive_scheme (see toggle above).
            elif state.drive_scheme == "QAWS" and k in (pygame.K_q, pygame.K_a, pygame.K_w, pygame.K_s):
                _mind_drive()   # wakes her first if she was asleep, so the key still drives
                if mode_manager.is_keyboard():
                    if k == pygame.K_q:   set_left_motor(motor_speed)
                    elif k == pygame.K_a: set_left_motor(-motor_speed)
                    elif k == pygame.K_w: set_right_motor(motor_speed)
                    elif k == pygame.K_s: set_right_motor(-motor_speed)
                    set_driving_lights()
                    pressed_keys.add(k)
            elif state.drive_scheme == "WASD" and k in (pygame.K_w, pygame.K_s, pygame.K_a, pygame.K_d):
                _mind_drive()
                if mode_manager.is_keyboard():
                    pressed_keys.add(k)
                    _apply_wasd(pressed_keys, motor_speed)   # W+A etc. curve instead of spinning

        elif event.type == pygame.KEYUP:
            if mode_manager.is_keyboard() and event.key in pressed_keys:
                pressed_keys.discard(event.key)
                if state.drive_scheme == "QAWS" and event.key in (pygame.K_q, pygame.K_a):
                    set_left_motor(0)
                    set_stopped_lights()
                elif state.drive_scheme == "QAWS" and event.key in (pygame.K_w, pygame.K_s):
                    set_right_motor(0)
                    set_stopped_lights()
                else:
                    # WASD: release W from W+A and she keeps turning left, etc.
                    _apply_wasd(pressed_keys, motor_speed)

        # ── Mouse ─────────────────────────────────────────────────────────────
        elif event.type == pygame.MOUSEBUTTONDOWN:
            pos = pygame.mouse.get_pos()
            for button in buttons:
                if button.is_clicked(pos):
                    is_play = (
                        hasattr(button, "label")
                        and button.label in ("Play", "▶", "Play Music")
                    )
                    # Ignore Play button while music is already playing
                    if is_play and music_ctrl and music_ctrl.is_playing():
                        continue
                    button.action()

    return signals
