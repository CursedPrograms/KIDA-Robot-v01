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
#   python3 main.py <robot-ip-or-url> [--port 5004] [--emulate]
#   ROBOT_URL=http://192.168.1.50:5004 python3 main.py
#   python3 main.py                 no robot: EMULATE, her pretend self on this PC (fake_kida01.py)
#
# On top of her own window, the PC's (fleet TODO section 13): EMULATE and STOP buttons,
# STOP / Backspace stop her in any mode (back to KEYBOARD), a drive key or the pad in any
# mode takes over (back to KEYBOARD, you drive), and a mode, scheme or music change is sent
# again until her /status says so.

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

import threading

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
import keymap           # controller/scripts/keymap.py — the keys window (F1) and the README
import mind_panel       # scripts/mind_panel.py: a MIND-mode mind's thinking, as in the other controllers
from drive_mind import DriveMind      # her MIND mode: this PC drives her when it can think
from options_link import OptionsLink  # her options (config.json): O / the Options button
import controller_kit as kit          # controller/controller_kit.py: settings that stick (every robot's)

APP_NAME = "KIDA — Remote Controller"
FAKE_URL = "http://127.0.0.1:5004"     # EMULATE: fake_kida01.py

_ORIGINAL = dict(hud_draw.C)           # DEFAULT: exactly her own HUD


def apply_theme(name, custom=None):
    """DEFAULT (her HUD's colours), LIGHT or CUSTOM (controller_settings.json), on this PC only."""
    hud_draw.C.update(_ORIGINAL)
    if name == "DEFAULT":
        return
    c = kit.theme_colours(name, custom)
    hud_draw.C.update(background=c["background"], hud=c["background"], hud_border=c["border"], panel=c["panel"],
                      panel_dark=c["background"], panel_btn=c["panel"], border=c["border"], border_cam=c["border"],
                      border_btn=c["border"], label=c["text_sec"], label2=c["text_sec"], heading=c["accent"],
                      text=c["text"], dim=c["text_dim"])


def _resolve_robot_url() -> tuple:
    """(robot URL or None, emulate)."""
    parser = argparse.ArgumentParser(description="KIDA remote controller")
    parser.add_argument(
        "robot", nargs="?", default=os.environ.get("ROBOT_URL"),
        help="Robot IP or URL, e.g. 192.168.1.50 or http://192.168.1.50:5004",
    )
    parser.add_argument("--port", type=int, default=5004)
    parser.add_argument("--emulate", action="store_true",
                        help="start on her pretend self (fake_kida01.py); the default with no robot given")
    parser.add_argument("--ladder", action="store_true",
                    help="join / host the fleet's WiFi (fleet_ladder.py; FLEET_LADDER=1 does the same)")
    args = parser.parse_args()
    from fleet_ladder import FleetLadder   # the fleet's WiFi ladder (fleet TODO, section 2)
    FleetLadder("KIDA01CTL", enabled=args.ladder or None).start()

    if not args.robot:
        return None, True

    robot = args.robot
    if not robot.startswith("http"):
        robot = f"http://{robot}:{args.port}"
    return robot, args.emulate


def _draw_disconnected_banner(screen, fonts, sw) -> None:
    msg = fonts["hd"].render("[ NO CONNECTION TO ROBOT ]", True, (255, 90, 90))
    screen.blit(msg, msg.get_rect(center=(sw // 2, 24)))


def run_controller() -> None:
    real_url, emulate = _resolve_robot_url()
    fake = {"robot": None}

    def start_fake() -> None:
        if fake["robot"] is None:
            try:
                import fake_kida01
                fake["robot"] = fake_kida01.FakeKida01()
                fake["robot"].quiet = True
            except OSError:              # port 5004 taken: a fake_kida01.py already running? use that
                print("EMULATE: port 5004 is taken; talking to whatever answers there")

    if emulate:
        start_fake()
    base_url = FAKE_URL if emulate else real_url
    print(f"▶ {APP_NAME} — connecting to {base_url}" + ("  (EMULATE: her pretend self)" if emulate else ""))
    remote  = RemoteClient(base_url)
    pending = kit.Pending()              # settings sent again until her /status says so

    def want(key, value, command) -> None:
        pending.want(key, value, lambda: threading.Thread(
            target=remote.send_action, args=(command,), daemon=True).start())

    def stop_anywhere() -> None:
        """STOP: motors off in any mode, back to KEYBOARD (as the pad's B, without stopping the music)."""
        if remote.status.get("mode", "KEYBOARD") != "KEYBOARD":
            want("mode", "KEYBOARD", "mode_1")
        threading.Thread(target=remote.send_action, args=("move_stop",), daemon=True).start()

    pygame.init()
    info   = pygame.display.Info()
    SW, SH = info.current_w, info.current_h
    screen = pygame.display.set_mode((SW, SH), pygame.RESIZABLE)
    pygame.display.set_caption(APP_NAME)
    try:  # window icon: the robot's avatar
        pygame.display.set_icon(pygame.image.load(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "images", "kida01-icon.png")))
    except (pygame.error, OSError):
        pass
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

    buttons      = create_buttons(remote, want)
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

    # Her options (config.json, the same menu as options.py on her), saved back with her PIN
    options = OptionsLink(remote)
    options_prompt = PasswordPrompt("HER PIN TO SAVE THE OPTIONS")
    options_btn = Button((0, 0, 160, 36), (200, 200, 160), "Options", options.open)
    buttons.extend([lock_btn, scheme_btn, chat_btn, options_btn])

    # The PC's own: STOP (any mode) and EMULATE (her pretend self on this PC, or back)
    def _emulate_click():
        nonlocal emulate, char_image
        if not emulate:
            start_fake()
        elif not real_url:
            return                       # no robot to go back to: she stays emulated
        emulate = not emulate
        remote.retarget(FAKE_URL if emulate else real_url)
        if not emulate and fake["robot"] is not None:
            fake["robot"].stop()
            fake["robot"] = None
        char_image = None
        print("EMULATE on: her pretend self" if emulate else f"EMULATE off: {real_url}")

    stop_btn = Button((0, 0, 160, 36), (255, 120, 120), "STOP", stop_anywhere)
    emulate_btn = Button((0, 0, 160, 36), (230, 200, 120), "EMULATE: ON" if emulate else "EMULATE: OFF", _emulate_click)
    settings = kit.Settings()              # controller_settings.json: the theme stays picked
    apply_theme(settings.theme, settings.get("custom"))

    def _theme_click():
        settings.next_theme()
        apply_theme(settings.theme, settings.get("custom"))
        theme_btn.text = theme_btn.label = f"THEME: {settings.theme}"

    theme_btn = Button((0, 0, 160, 36), (170, 220, 230), f"THEME: {settings.theme}", _theme_click)
    buttons.extend([stop_btn, emulate_btn, theme_btn])

    char_image          = None
    # MIND mode (9): this PC's LLM drives her when it can think and her
    # config.json Mind/Where lets it; otherwise her own Pi might (shown the same)
    brain = DriveMind(remote)

    last_photo_surf     = None
    last_photo_ts_seen  = None
    pressed_keys        = set()
    show_keys           = False   # the keys window (F1)
    clock                = pygame.time.Clock()
    running               = True

    print("🎮 Keys: 1=KB 2=IR 3=AUTO 4=IDLE | I=infer | M=music | U=lock/unlock | SPC=stop | Q/ESC=close | F1=all keys")
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
        screen.fill(hud_draw.C["background"])

        hud_draw.draw_static_panel(screen, char_image, FACE_RECT,
                                   "KIDA", fonts["xs"], fonts["nosig"])
        hud_draw.draw_camera_panel(screen, remote.frame1, CAM1_RECT,
                                   "Cam 1", fonts["xs"], fonts["nosig"])
        hud_draw.draw_camera_panel(screen, remote.frame0, CAM0_RECT,
                                   "Cam 0", fonts["xs"], fonts["nosig"])
        hud_draw.draw_static_panel(screen, last_photo_surf, PHOTO_RECT,
                                   "Last Photo Taken", fonts["xs"], fonts["nosig"])

        hud_draw.draw_panel(screen, HUD_RECT, fill=hud_draw.C["hud"], alpha=218,
                            border=hud_draw.C["hud_border"], radius=0)

        at     = remote.status_at   # first: the status read after it is at least that new
        status = remote.status
        pending.check(status, at)
        emulate_btn.text = emulate_btn.label = "EMULATE: ON" if emulate else "EMULATE: OFF"
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
        brain.update(status)
        driving_mind, where = brain.shown(status)
        if driving_mind is not None:
            mind_panel.draw(screen, MIND_RECT, driving_mind, fonts["sm"], fonts["xs"], "KIDA-01", note=where)
        else:
            hud_draw.draw_mind_panel(screen, fonts, MIND_RECT, remote.mind)

        if mode_manager.is_idle():
            hud_draw.draw_idle_overlay(screen, fonts)

        if not remote.connected:
            _draw_disconnected_banner(screen, fonts, SW)
        elif emulate:
            note = fonts["xs"].render("EMULATE: her pretend self on this PC (fake_kida01.py)", True, (255, 190, 80))
            screen.blit(note, (12, SH - note.get_height() - 6))

        lock_prompt.draw(screen, fonts)
        chat_prompt.draw(screen, fonts)
        options_prompt.draw(screen, fonts)
        if show_keys:
            keymap.draw(screen)

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
        if options.pending is not None and not (lock_prompt.active or chat_prompt.active or options_prompt.active):
            edited, options.pending = options.pending, None   # ESC on the prompt drops the edit
            options_prompt.open(lambda pin, d=edited: options.send(pin, d))
        if lock_prompt.active or chat_prompt.active or options_prompt.active:
            prompt = (lock_prompt if lock_prompt.active else chat_prompt if chat_prompt.active
                      else options_prompt)
            for event in raw_events:
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    prompt.handle_key(event)
            continue

        # The keys window: F1 opens it; while it's open F1 / ESC close it and other keys do nothing
        if show_keys:
            for event in raw_events:
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN and event.key in (pygame.K_F1, pygame.K_ESCAPE):
                    show_keys = False
            continue
        if any(e.type == pygame.KEYDOWN and e.key == pygame.K_F1 for e in raw_events):
            show_keys = True
            continue
        if any(e.type == pygame.KEYDOWN and e.key == pygame.K_o for e in raw_events):
            options.open()

        sigs = event_handler.handle_events(raw_events, buttons, pressed_keys, remote,
                                           lock_prompt=lock_prompt, chat_prompt=chat_prompt,
                                           want=want, stop_anywhere=stop_anywhere)
        # the pad drives in any mode too: it takes over (back to KEYBOARD, you drive)
        with joystick._lock:
            pad_driving = any(joystick._target)
        if pad_driving and status.get("mode", "KEYBOARD") != "KEYBOARD" and pending.value("mode") != "KEYBOARD":
            print(f"Driving takes over (pad): {status.get('mode')} -> KEYBOARD")
            want("mode", "KEYBOARD", "mode_1")
        event_handler.drive_heartbeat(pressed_keys, remote)
        if sigs["quit"]:
            running = False

    # ── Cleanup — release any held drive key so the robot doesn't keep
    #    moving after this window closes ──
    for _ in list(pressed_keys):
        remote.send_action("move_stop")
    if brain.mind.on:
        brain.mind.stop()
    joystick.stop()
    remote.stop()
    if fake["robot"] is not None:
        fake["robot"].stop()
    pygame.quit()
    print("✅ Controller closed")


if __name__ == "__main__":
    run_controller()
