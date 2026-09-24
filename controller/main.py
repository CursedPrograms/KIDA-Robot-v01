# main.py — KIDA remote controller
#
# Runs on a separate PC (its own venv, no picamera2/RPi.GPIO/Hailo — see
# requirements.txt) and renders the exact same HUD as the robot's own
# scripts/ui.py: same layout (hud_layout.py), same drawing code
# (hud_draw.py), same button widget (button_widget.py). Only the data
# source differs — camera frames, sensor readings and control commands
# travel over the network via remote_client.py to the robot's Flask
# server (scripts/server.py) instead of touching local hardware.
#
# Because the layout/drawing/button-widget modules are literally the same
# files the robot imports (scripts/ is on sys.path below), a visual change
# made once — panel order, colors, fonts — applies to both HUDs together.
#
# Usage:
#   python3 main.py <robot-ip-or-url> [--port 5004]
#   ROBOT_URL=http://192.168.1.50:5004 python3 main.py

import argparse
import os
import sys

_HERE        = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_DIR = os.path.join(os.path.dirname(_HERE), "scripts")
_SHIMS_DIR   = os.path.join(_HERE, "scripts")

# scripts/ — the shared, hardware-agnostic modules (state.py, hud_draw.py,
# hud_layout.py, button_widget.py). Inserted first...
sys.path.insert(0, _SCRIPTS_DIR)
# ...then controller/scripts/, so it takes priority for any same-named module
# the robot side implements with real hardware (mode_manager.py,
# camera_actions.py, buttons.py) — this dir's shims win the lookup.
sys.path.insert(0, _SHIMS_DIR)

import pygame

import state
import hud_draw
import hud_layout
import mode_manager
from button_widget import Button
from password_prompt import PasswordPrompt
from text_prompt import TextPrompt
from buttons import create_buttons
from remote_client import RemoteClient
from joystick_drive import JoystickDrive
import event_handler

APP_NAME = "KIDA — Remote Controller"


def _resolve_robot_url() -> str:
    parser = argparse.ArgumentParser(description="KIDA remote controller")
    parser.add_argument(
        "robot", nargs="?", default=os.environ.get("ROBOT_URL"),
        help="Robot IP or URL, e.g. 192.168.1.50 or http://192.168.1.50:5004",
    )
    parser.add_argument("--port", type=int, default=5004)
    args = parser.parse_args()

    if not args.robot:
        parser.error("robot IP/URL required (positional arg, or ROBOT_URL env var)")

    robot = args.robot
    if not robot.startswith("http"):
        robot = f"http://{robot}:{args.port}"
    return robot


def _draw_disconnected_banner(screen, fonts, sw) -> None:
    msg = fonts["hd"].render("[ NO CONNECTION TO ROBOT ]", True, (255, 90, 90))
    screen.blit(msg, msg.get_rect(center=(sw // 2, 24)))


def run_controller() -> None:
    base_url = _resolve_robot_url()
    print(f"▶ {APP_NAME} — connecting to {base_url}")
    remote = RemoteClient(base_url)

    pygame.init()
    info   = pygame.display.Info()
    SW, SH = info.current_w, info.current_h
    screen = pygame.display.set_mode((SW, SH), pygame.RESIZABLE)
    pygame.display.set_caption(APP_NAME)
    pygame.mouse.set_visible(True)

    fonts = {
        "sm":    pygame.font.SysFont("monospace", 16),
        "xs":    pygame.font.SysFont("monospace", 13),
        "md":    pygame.font.SysFont("monospace", 19),
        "hd":    pygame.font.SysFont("monospace", 21),
        "nosig": pygame.font.SysFont("monospace", 15),
    }

    # ── Layout — identical to ui.py, computed by the same shared function ──
    layout         = hud_layout.compute_layout(SW, SH)
    FACE_RECT      = layout["face_rect"]
    CAM1_RECT      = layout["cam1_rect"]
    CAM0_RECT      = layout["cam0_rect"]
    PHOTO_RECT     = layout["photo_rect"]
    HUD_RECT       = layout["hud_rect"]
    hud_y          = layout["hud_y"]
    SEN_X1         = layout["sen_x1"]
    SEN_X2         = layout["sen_x2"]
    SEN_TOP        = layout["sen_top"]
    btn_panel_x    = layout["btn_panel_x"]
    btn_panel_rect = layout["btn_panel_rect"]
    MIND_RECT      = hud_draw.mind_panel_rect(SW, SH, hud_y, SEN_X2, btn_panel_x)

    buttons      = create_buttons(remote)
    lbl_surfaces = [
        fonts["xs"].render(f"{lbl}:", True, (100, 130, 185))
        for _, lbl in hud_layout.SENSOR_ROWS
    ]

    # ── Motor lock + drive scheme toggle — same widgets/prompt as ui.py.
    #    Used to float at fixed top-left coordinates, which overlapped the
    #    face camera panel (hud_layout.compute_layout puts face_rect at
    #    roughly (12, 12) sized up to 40% of screen height). Now folded
    #    into the auto-arranged button grid instead — hud_draw.py's
    #    draw_button_panel() special-cases their labels each frame.
    #    Unlocking asks the robot to check the password (never checked
    #    locally, so the controller never needs to know it).
    lock_prompt = PasswordPrompt("ENTER PASSWORD TO UNLOCK MOTORS")

    def _motor_lock_click():
        if state.motor_lock:
            lock_prompt.open(lambda pw: remote.send_action("motor_lock_off", password=pw))
        else:
            remote.send_action("motor_lock_on")

    lock_btn = Button((0, 0, 160, 36), (140, 200, 140), "Lock Motors", _motor_lock_click)

    # Gamepad on this PC — Start mirrors the Lock Motors button.
    joystick = JoystickDrive(remote, on_unlock_request=_motor_lock_click)

    # Drive scheme toggle — WASD (differential) vs QAWS (tank, Q/A=left
    # motor, W/S=right motor). state.drive_scheme is kept in sync with
    # the robot by remote_client.py's /status poll.
    def _drive_scheme_click():
        remote.send_action("scheme_qaws" if state.drive_scheme == "WASD" else "scheme_wasd")

    scheme_btn = Button((0, 0, 160, 36), (160, 160, 220), "Scheme: WASD", _drive_scheme_click)

    # Typing to her from this PC — goes into the same queue as her voice
    # conversations; her answer shows in the mind panel (you may not hear her).
    chat_prompt = TextPrompt("TYPE A MESSAGE TO KIDA")

    def _chat_click():
        chat_prompt.open(lambda text: remote.send_action("chat", text=text))

    chat_btn = Button((0, 0, 160, 36), (160, 200, 220), "Type to KIDA", _chat_click)
    buttons.extend([lock_btn, scheme_btn, chat_btn])

    char_image          = None
    last_photo_surf     = None
    last_photo_ts_seen  = None
    pressed_keys        = set()
    clock                = pygame.time.Clock()
    running               = True

    print("🎮 Keys: 1=KB 2=IR 3=AUTO 4=IDLE | I=infer | M=music | U=lock/unlock | SPC=stop | Q/ESC=close")
    print("🕹️  Joystick (KEYBOARD mode): L-stick=drive (tank scheme: LT/RT tracks, LB/RB reverse) R-stick=servo | A=photo B=stop X/Y=speed -/+ | D-pad L/R=mode Up=video Start=lock Back=sweep")

    while running:
        # ── Character face — fetched once, on first successful connection ──
        if char_image is None and remote.connected:
            surf = remote.fetch_image("/character_face")
            if surf is not None:
                char_image = pygame.transform.smoothscale(surf, FACE_RECT.size)

        # ── "Last photo" panel — refetch only when the robot reports a new one ──
        if remote.last_photo_ts != last_photo_ts_seen:
            last_photo_ts_seen = remote.last_photo_ts
            last_photo_surf = None
            if last_photo_ts_seen:
                surf = remote.fetch_image(f"/last_photo?t={last_photo_ts_seen}")
                if surf is not None:
                    last_photo_surf = pygame.transform.smoothscale(surf, PHOTO_RECT.size)

        # ════════════════════════════════
        #  RENDER — same draw calls as ui.py, fed from network data
        # ════════════════════════════════
        screen.fill((7, 9, 16))

        hud_draw.draw_static_panel(screen, char_image, FACE_RECT,
                                   "KIDA", fonts["xs"], fonts["nosig"])
        hud_draw.draw_camera_panel(screen, remote.frame1, CAM1_RECT,
                                   "Cam 1", fonts["xs"], fonts["nosig"])
        hud_draw.draw_camera_panel(screen, remote.frame0, CAM0_RECT,
                                   "Cam 0", fonts["xs"], fonts["nosig"])
        hud_draw.draw_static_panel(screen, last_photo_surf, PHOTO_RECT,
                                   "Last Photo Taken", fonts["xs"], fonts["nosig"])

        hud_draw.draw_panel(screen, HUD_RECT, fill=(7, 11, 20), alpha=218,
                            border=(32, 52, 88), radius=0)

        status = remote.status
        hud_draw.draw_status_strip(
            screen, fonts, hud_y, SEN_X1,
            status.get("motor_speed", "—"), status.get("cpu_temp", "N/A"),
            status.get("cpu", 0.0), status.get("ram", 0.0), status.get("ip", base_url),
            status.get("inference_on", False),
            status.get("bus_v", 0.0), status.get("cur_ma", 0.0),
            status.get("pwr_w", 0.0), status.get("bat_pct", 0.0),
            status.get("music_on", False),
        )
        hud_draw.draw_sensor_grid(
            screen, fonts, hud_layout.SENSOR_ROWS, lbl_surfaces,
            SEN_X1, SEN_X2, SEN_TOP,
        )
        hud_draw.draw_button_panel(
            screen, fonts, buttons, hud_y, btn_panel_x, btn_panel_rect,
            status.get("music_on", False),
        )
        hud_draw.draw_mind_panel(screen, fonts, MIND_RECT, remote.mind)

        if mode_manager.is_idle():
            hud_draw.draw_idle_overlay(screen, fonts)

        if not remote.connected:
            _draw_disconnected_banner(screen, fonts, SW)

        lock_prompt.draw(screen, fonts)
        chat_prompt.draw(screen, fonts)

        pygame.display.flip()
        clock.tick(30)

        # ════════════════════════════════
        #  EVENTS
        # ════════════════════════════════
        raw_events = pygame.event.get()

        # Joystick first, so releasing the stick still reaches the robot
        # even while the unlock prompt below is swallowing input.
        joystick.handle_events(raw_events)

        # While the unlock prompt is open, every key goes to it — nothing
        # else (mode switches, drive keys, buttons) should fire mid-entry.
        if lock_prompt.active or chat_prompt.active:
            prompt = lock_prompt if lock_prompt.active else chat_prompt
            for event in raw_events:
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    prompt.handle_key(event)
            continue

        sigs = event_handler.handle_events(raw_events, buttons, pressed_keys, remote,
                                           lock_prompt=lock_prompt, chat_prompt=chat_prompt)
        event_handler.drive_heartbeat(pressed_keys, remote)
        if sigs["quit"]:
            running = False

    # ── Cleanup — release any held drive key so the robot doesn't keep
    #    moving after this window closes ──
    for _ in list(pressed_keys):
        remote.send_action("move_stop")
    joystick.stop()
    remote.stop()
    pygame.quit()
    print("✅ Controller closed")


if __name__ == "__main__":
    run_controller()
