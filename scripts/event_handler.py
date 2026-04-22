# event_handler.py — keyboard and mouse event dispatch for KIDA
#
# Music is handled directly here via the music_ctrl MusicPlayer instance
# passed in from ui.py, so this module has zero music-module imports.
#
# Returns a signals dict so ui.py stays thin:
#   quit             bool
#   inference_toggle bool
#   char_next        bool
#   motor_speed      int

import pygame
import config
import leds
import mode_manager

from state import DriveMode
from arduino import send_command
from mode_control import switch_mode, switch_mode_direct


def handle_events(events, buttons: list,
                  pressed_keys: set,
                  motor_speed: int,
                  inference_on: bool,
                  char_imgs: list, char_idx: int,
                  music_ctrl=None) -> dict:
    """
    Process all pending pygame events.
    music_ctrl is the MusicPlayer instance from ui.py (optional; safe to omit).
    """
    signals = {
        "quit":             False,
        "inference_toggle": False,
        "char_next":        False,
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

            # Quit
            elif k in (pygame.K_q, pygame.K_ESCAPE):
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
                send_command("dev00", f"SPEED:{signals['motor_speed']}")
                print(f"⚡ Speed: {signals['motor_speed']}")

            # Hard stop — motors + music
            elif k == pygame.K_SPACE:
                send_command("dev00", "STOP")
                send_command("dev01", "LIGHT_FRONT_OFF")
                send_command("dev01", "LIGHT_BACK_ON")
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

            # Character avatar cycle
            elif k == pygame.K_c and char_imgs:
                signals["char_next"] = True

            # Movement — KEYBOARD mode only
            elif k in (pygame.K_w, pygame.K_s, pygame.K_a, pygame.K_d):
                if mode_manager.is_keyboard():
                    direction = {
                        pygame.K_w: "FORWARD",
                        pygame.K_s: "BACKWARD",
                        pygame.K_a: "LEFT",
                        pygame.K_d: "RIGHT",
                    }[k]
                    send_command("dev00", direction)
                    send_command("dev01", "LIGHT_FRONT_ON")
                    send_command("dev01", "LIGHT_BACK_OFF")
                    leds.toggle_leds()
                    pressed_keys.add(k)

        elif event.type == pygame.KEYUP:
            if mode_manager.is_keyboard() and event.key in pressed_keys:
                send_command("dev00", "STOP")
                send_command("dev01", "LIGHT_FRONT_OFF")
                send_command("dev01", "LIGHT_BACK_ON")
                pressed_keys.discard(event.key)

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
