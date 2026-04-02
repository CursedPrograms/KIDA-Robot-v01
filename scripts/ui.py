# ui.py — KIDA main UI
#
# Drive modes (select with keys 1-4 or matching IR signal — always available):
#   1 → KEYBOARD    WASD to drive
#   2 → IR_REMOTE   IR handset drives
#   3 → AUTONOMOUS  AI / state-machine drives
#   4 → IDLE        all motors stop, black input state
#
# Other keys (work in any mode unless noted):
#   W/A/S/D  — move          (KEYBOARD mode only)
#   SPACE    — hard stop motors + music
#   I        — toggle YOLO inference on cam-0
#   X        — cycle motor speed
#   M        — play / skip music  (re-enables after SPACE)
#   L        — toggle LEDs
#   K        — toggle LED effects
#   C        — cycle character avatar
#   Q / ESC  — quit
import sys
import cv2
import pygame
import time
import os
import threading
import json
import platform

import config
import leds
import music
import state
import mode_manager

from state import DriveMode
from buttons import create_buttons
from arduino import send_command, start_arduino_threads
from mpu6050_module import start_mpu_thread
from stats import get_cpu_temp, get_system_stats, get_local_ip
from camera_actions import check_recording_timeout
from ina219_module import INA219
from picamera2 import Picamera2
from queue import Queue, Empty
import RPi.GPIO as GPIO
from mode_manager import register_on_mode_change
from mode_hooks import universal_mode_change
# ─────────────────────────────────────────────
#  Startup (runs at import time — before pygame.init)
# ─────────────────────────────────────────────
with open("./config.json") as f:
    _cfg = json.load(f)

# ── Project root ──
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, BASE_DIR)

APP_NAME   = _cfg.get("Config", {}).get("AppName", "KIDA")
PYTHON_CMD = "python" if platform.system() == "Windows" else "python3"
print(f"▶ {APP_NAME}")

time.sleep(2)
pygame.mixer.pre_init(44100, -16, 2, 1024)
pygame.mixer.init()
pygame.mixer.music.load("./audio/startup.mp3")
pygame.mixer.music.play()
while pygame.mixer.music.get_busy():
    pygame.time.Clock().tick(10)

# ─────────────────────────────────────────────
#  Layout constants
# ─────────────────────────────────────────────
CAM_PAD    = 12
CAM_H_FRAC = 0.56   # cameras take top 56 % of screen height

# ─────────────────────────────────────────────
#  Sensor rows shown in HUD
# ─────────────────────────────────────────────
SENSOR_ROWS = [
    ("photoValue",       "Photo"),
    ("uvValue",          "UV"),
    ("metalValue",       "Metal"),
    ("ballSwitchValue",  "Ball Sw"),
    ("motionValue",      "Motion"),
    ("lfLeftValue",      "LF L"),
    ("lfMidValue",       "LF M"),
    ("lfRightValue",     "LF R"),
    ("laserValue",       "Laser"),
    ("ultrasonic0Value", "US0"),
    ("ultrasonic1Value", "US1"),
    ("mpu_ax",           "AX"),
    ("mpu_ay",           "AY"),
    ("mpu_az",           "AZ"),
    ("mpu_gx",           "GX"),
    ("mpu_gy",           "GY"),
    ("mpu_gz",           "GZ"),
    ("systemStatus",     "Status"),
]

# ─────────────────────────────────────────────
#  Mode display config
# ─────────────────────────────────────────────
_MODE_LABEL = {
    DriveMode.KEYBOARD:   ("KB",   (100, 220, 140)),
    DriveMode.IR_REMOTE:  ("IR",   (100, 180, 255)),
    DriveMode.AUTONOMOUS: ("AUTO", (255, 190,  80)),
    DriveMode.IDLE:       ("IDLE", (180,  80,  80)),
}

# ─────────────────────────────────────────────
#  Global runtime state
# ─────────────────────────────────────────────
motor_speed     = config.DEFAULT_SPEED
pressed_keys    = set()
music_blocked   = False

frame_queue     = Queue(maxsize=1)   # cam-0 (main / inference)
frame_queue2    = Queue(maxsize=1)   # cam-1 (AI)
cam0_stop_event = threading.Event()

# ─────────────────────────────────────────────
#  Camera threads
# ─────────────────────────────────────────────
def _camera_loop(picam2, model, task, queue, stop_event):
    """Cam-0: optional YOLO inference. Exits when stop_event is set."""
    while not stop_event.is_set():
        try:
            frame = picam2.capture_array()
            if frame is None:
                continue
            if model and task == "detect":
                results = model.predict(frame, conf=0.5, verbose=False)
                out = results[0].plot()
            else:
                out = frame
            out = cv2.cvtColor(out, cv2.COLOR_BGR2RGB)
            out = cv2.flip(out, 1)
            if not queue.empty():
                try:
                    queue.get_nowait()
                except Empty:
                    pass
            queue.put(out)
        except Exception as e:
            print(f"[Cam0] {e}")
            time.sleep(0.05)


def _camera2_loop(cam, queue):
    """Cam-1: always-on feed, no inference."""
    while True:
        try:
            frame = cam.capture_array()
            if frame is None:
                continue
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame = cv2.flip(frame, 1)
            if not queue.empty():
                try:
                    queue.get_nowait()
                except Empty:
                    pass
            queue.put(frame)
        except Exception as e:
            print(f"[Cam1] {e}")
            time.sleep(0.05)

# ─────────────────────────────────────────────
#  Music helpers
# ─────────────────────────────────────────────
def hard_stop_music():
    global music_blocked
    music_blocked = True
    for fn in (pygame.mixer.music.stop, pygame.mixer.stop, music.stop_music):
        try:
            fn()
        except Exception:
            pass


def safe_play_next():
    if not music_blocked:
        music.play_next_track()


def safe_skip():
    if not music_blocked:
        music.skip_music()

# ─────────────────────────────────────────────
#  Draw helpers  (Surface cache — no per-frame alloc)
# ─────────────────────────────────────────────
_panel_cache: dict = {}

def draw_panel(surface, rect, fill=(14, 18, 30), alpha=210,
               border=(50, 70, 110), radius=6):
    key = (rect.size, fill, alpha, border, radius)
    if key not in _panel_cache:
        s = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(s, (*fill, alpha), s.get_rect(), border_radius=radius)
        pygame.draw.rect(s, (*border, 255), s.get_rect(), width=1, border_radius=radius)
        _panel_cache[key] = s
    surface.blit(_panel_cache[key], rect.topleft)


def draw_camera_panel(surface, frame, rect, label, label_font, nosig_font):
    if frame is not None:
        try:
            surf = pygame.surfarray.make_surface(frame.swapaxes(0, 1))
            surf = pygame.transform.scale(surf, rect.size)
            surface.blit(surf, rect.topleft)
        except Exception as e:
            print(f"[Draw {label}] {e}")
    else:
        draw_panel(surface, rect, fill=(8, 10, 18), alpha=240)
        sig = nosig_font.render(f"[ {label} — NO SIGNAL ]", True, (60, 75, 100))
        surface.blit(sig, sig.get_rect(center=rect.center))
    pygame.draw.rect(surface, (50, 72, 115), rect, 2)
    tag = label_font.render(label, True, (150, 185, 255))
    surface.blit(tag, (rect.x + 6, rect.y + 5))

# ─────────────────────────────────────────────
#  Celebration (move to emotions.py eventually)
# ─────────────────────────────────────────────
_celebration_lock   = threading.Lock()
_celebration_active = False


def celebration_routine():
    global _celebration_active
    print("🎉 Celebration!")
    threading.Thread(target=leds.run_chase_effect, daemon=True).start()
    safe_play_next()
    send_command("dev00", "HAPPY")
    time.sleep(15)
    with _celebration_lock:
        _celebration_active = False

# ─────────────────────────────────────────────
#  IR bridge  (polled each frame)
# ─────────────────────────────────────────────
_last_ir_command = None
_last_ir_mode    = None


def _poll_ir():
    """
    Read state.irCommand / state.irMode written by arduino.py and act on them.
    Mode signals map to mode_manager; movement signals only act in IR_REMOTE mode.
    Called once per frame from the main loop.
    """
    global _last_ir_command, _last_ir_mode, motor_speed

    # ── Mode change via IR ──
    ir_mode = getattr(state, "irMode", None)
    if ir_mode and ir_mode != _last_ir_mode:
        _last_ir_mode = ir_mode
        _IR_MODE_MAP = {
            "IR_REMOTE":  DriveMode.IR_REMOTE,
            "KEYBOARD":   DriveMode.KEYBOARD,
            "AUTO":       DriveMode.AUTONOMOUS,
            "IDLE":       DriveMode.IDLE,
        }
        if ir_mode in _IR_MODE_MAP:
            mode_manager.set_mode(_IR_MODE_MAP[ir_mode])

    # ── Commands (only acted on in IR_REMOTE mode) ──
    cmd = getattr(state, "irCommand", None)
    if cmd == _last_ir_command:
        return
    _last_ir_command = cmd
    if not cmd or cmd == "-":
        return

    print(f"🎮 IR cmd: {cmd}")

    # Mode-select by number also works from IR
    if cmd in ("MODE1", "1"):
        # Register the universal mode hook        
        mode_manager.set_mode_by_number(1); 
        register_on_mode_change(universal_mode_change)
        return
    if cmd in ("MODE2", "2"):
        mode_manager.set_mode_by_number(2); 
        register_on_mode_change(universal_mode_change)
        return
    if cmd in ("MODE3", "3"):
        mode_manager.set_mode_by_number(3); 
        register_on_mode_change(universal_mode_change)
        return
    if cmd in ("MODE4", "4"):
        mode_manager.set_mode_by_number(4);
        register_on_mode_change(universal_mode_change) 
        return

    # Movement — IR_REMOTE mode only
    if not mode_manager.is_ir():
        return

    if cmd == "FORWARD":
        send_command("dev00", "FORWARD")
        send_command("dev01", "LIGHT_FRONT_ON")
        send_command("dev01", "LIGHT_BACK_OFF")
    elif cmd == "BACKWARD":
        send_command("dev00", "BACKWARD")
        send_command("dev01", "LIGHT_FRONT_ON")
        send_command("dev01", "LIGHT_BACK_OFF")
    elif cmd == "LEFT":
        send_command("dev00", "LEFT")
        send_command("dev01", "LIGHT_FRONT_ON")
        send_command("dev01", "LIGHT_BACK_OFF")
    elif cmd == "RIGHT":
        send_command("dev00", "RIGHT")
        send_command("dev01", "LIGHT_FRONT_ON")
        send_command("dev01", "LIGHT_BACK_OFF")
    elif cmd == "STOP":
        send_command("dev00", "STOP")
        send_command("dev01", "LIGHT_FRONT_OFF")
        send_command("dev01", "LIGHT_BACK_ON")
    elif cmd == "PLAY":
        music.play_next_track()
    elif cmd == "SPEED_UP":
        motor_speed = min(motor_speed + config.SPEED_STEP, config.MAX_SPEED)
        send_command("dev00", f"SPEED:{motor_speed}")
    elif cmd == "NEXT_MODE":
        # Toggle between IR and KEYBOARD
        if mode_manager.is_ir():
            mode_manager.set_mode(DriveMode.KEYBOARD)
        else:
            mode_manager.set_mode(DriveMode.IR_REMOTE)

# ─────────────────────────────────────────────
#  IDLE overlay
# ─────────────────────────────────────────────
def _draw_idle_overlay(surface, fonts):
    """Full-screen dark overlay shown in IDLE mode."""
    overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 220))
    surface.blit(overlay, (0, 0))
    msg = fonts["hd"].render("[ IDLE — press 1 / 2 / 3 to select a mode ]",
                              True, (140, 60, 60))
    surface.blit(msg, msg.get_rect(center=(surface.get_width() // 2,
                                           surface.get_height() // 2)))

# ─────────────────────────────────────────────
#  Main UI entry point
# ─────────────────────────────────────────────
def run_ui(model=None, mode="cam", task="detect", tracker_path=None):
    global motor_speed, pressed_keys, music_blocked, cam0_stop_event

    pygame.init()

    # ── Background services ──
    try:
        start_arduino_threads()
    except Exception as e:
        print(f"⚠️ Arduino threads: {e}")
    try:
        start_mpu_thread()
    except Exception as e:
        print(f"⚠️ MPU thread: {e}")

    # ── Display ──
    info = pygame.display.Info()
    SW, SH = info.current_w, info.current_h
    screen = pygame.display.set_mode((SW, SH), pygame.FULLSCREEN)
    pygame.display.set_caption(APP_NAME)
    pygame.mouse.set_visible(True)

    # ── Fonts ──
    fonts = {
        "sm":    pygame.font.SysFont("monospace", 16),
        "xs":    pygame.font.SysFont("monospace", 13),
        "md":    pygame.font.SysFont("monospace", 19),
        "hd":    pygame.font.SysFont("monospace", 21),
        "nosig": pygame.font.SysFont("monospace", 15),
    }

    # ── Layout ──
    cam_top  = CAM_PAD
    cam_h    = int(SH * CAM_H_FRAC)
    cam_w    = (SW - CAM_PAD * 3) // 2

    CAM0_RECT = pygame.Rect(CAM_PAD,              cam_top, cam_w, cam_h)
    CAM1_RECT = pygame.Rect(CAM_PAD * 2 + cam_w, cam_top, cam_w, cam_h)

    hud_y    = cam_top + cam_h + CAM_PAD
    hud_h    = SH - hud_y
    HUD_RECT = pygame.Rect(0, hud_y, SW, hud_h)

    SEN_X1  = 14
    SEN_X2  = SEN_X1 + 280
    SEN_TOP = hud_y + 46

    btn_panel_x    = SW - 320
    btn_panel_rect = pygame.Rect(btn_panel_x - 6, hud_y + 2,
                                  SW - btn_panel_x + 4, hud_h - 4)


    # ── Hardware ──
    ina219_module = None
    try:
        ina219_module = INA219(addr=0x41)
    except Exception as e:
        print(f"⚠️ INA219: {e}")

    leds.setup_leds()
    leds.startup_led_fade()
    #send_command("dev00", "RAINBOW")
    music.init_music()

    # ── Assets ──
    char_imgs = []
    for fname in sorted(os.listdir(config.CHARACTER_FOLDER)):
        if fname.lower().endswith((".jpg", ".jpeg", ".png")):
            img = pygame.image.load(
                os.path.join(config.CHARACTER_FOLDER, fname)
            ).convert_alpha()
            char_imgs.append(pygame.transform.smoothscale(img, (80, 80)))
    char_idx   = 0
    char_image = char_imgs[char_idx] if char_imgs else None

    bg = pygame.image.load(config.BACKGROUND_IMAGE).convert()
    bg = pygame.transform.smoothscale(bg, (SW, SH))
    bg.set_alpha(28)

    buttons = create_buttons()

    # Pre-render static sensor label surfaces
    lbl_surfaces = [
        fonts["xs"].render(f"{lbl}:", True, (100, 130, 185))
        for _, lbl in SENSOR_ROWS
    ]

    # ── Cameras ──
    picam2      = None
    picam2_ai   = None
    inference_on  = False
    cam0_thread   = None
    last_frame0   = None
    last_frame1   = None

    if mode == "cam":
        try:
            picam2 = Picamera2(camera_num=0)
            picam2.configure(picam2.create_preview_configuration(
                main={"format": "RGB888", "size": (640, 480)}))
            picam2.start()
            print("✅ Cam-0 ready")
        except Exception as e:
            print(f"❌ Cam-0: {e}")

        try:
            picam2_ai = Picamera2(camera_num=1)
            picam2_ai.configure(picam2_ai.create_preview_configuration(
                main={"format": "RGB888", "size": (640, 480)}))
            picam2_ai.start()
            threading.Thread(
                target=_camera2_loop, args=(picam2_ai, frame_queue2), daemon=True
            ).start()
            print("✅ Cam-1 ready")
        except Exception as e:
            print(f"❌ Cam-1: {e}")

    def start_inference():
        nonlocal cam0_thread, inference_on
        if picam2 is None:
            return
        cam0_stop_event.clear()
        cam0_thread = threading.Thread(
            target=_camera_loop,
            args=(picam2, model, task, frame_queue, cam0_stop_event),
            daemon=True,
        )
        cam0_thread.start()
        inference_on = True
        print("✅ Inference ON")

    def stop_inference():
        nonlocal inference_on
        cam0_stop_event.set()
        inference_on = False
        while not frame_queue.empty():
            try:
                frame_queue.get_nowait()
            except Empty:
                break
        print("🛑 Inference OFF")

    # ── Main loop vars ──
    clock           = pygame.time.Clock()
    running         = True
    last_stats_time = 0
    STATS_INTERVAL  = 2.0
    cpu = ram = 0
    cpu_temp = "N/A"
    bus_v = cur_ma = pwr_w = bat_pct = 0.0

    # Start in KEYBOARD mode
    mode_manager.set_mode(DriveMode.KEYBOARD, stop_motors=False)
    print("🎮 Keys: 1=KB 2=IR 3=AUTO 4=IDLE | I=infer | M=music | SPC=stop | Q=quit")

    # ═══════════════════════════════════════════
    #  MAIN LOOP
    # ═══════════════════════════════════════════
    while running:
        now = time.time()
        check_recording_timeout()

        # ── Poll IR bridge every frame ──
        _poll_ir()

        # ── Stats (throttled to every 2 s) ──
        if now - last_stats_time > STATS_INTERVAL:
            cpu_temp = get_cpu_temp()
            cpu, ram = get_system_stats()
            if ina219_module is not None:
                try:
                    bus_v   = ina219_module.getBusVoltage_V()
                    cur_ma  = ina219_module.getCurrent_mA()
                    pwr_w   = ina219_module.getPower_W()
                    bat_pct = max(0.0, min(100.0, (bus_v - 9.0) / 3.6 * 100.0))
                except Exception:
                    bus_v = cur_ma = pwr_w = bat_pct = 0.0
            last_stats_time = now

        # ── Pull camera frames ──
        try:
            last_frame0 = frame_queue.get_nowait()
        except Empty:
            pass
        try:
            last_frame1 = frame_queue2.get_nowait()
        except Empty:
            pass

        # ════════════════════════════════
        #  RENDER
        # ════════════════════════════════
        screen.fill((7, 9, 16))
        screen.blit(bg, (0, 0))

        draw_camera_panel(screen, last_frame1, CAM1_RECT,
                          "SLOT 1 — AI CAM", fonts["xs"], fonts["nosig"])
        draw_camera_panel(screen, last_frame0, CAM0_RECT,
                          "SLOT 0 — MAIN",   fonts["xs"], fonts["nosig"])

        if char_image:
            screen.blit(char_image, (CAM_PAD, hud_y - 84))

        # HUD background
        draw_panel(screen, HUD_RECT, fill=(7, 11, 20), alpha=218,
                   border=(32, 52, 88), radius=0)

        # Current mode label + colour
        cur_mode                   = mode_manager.current_mode()
        mode_label, mode_color     = _MODE_LABEL.get(cur_mode, ("???", (200, 200, 200)))
        music_on                   = music.is_music_playing()
        music_sym                  = "▶" if music_on else "■"
        local_ip                   = get_local_ip()

        # Power strip
        pw = fonts["sm"].render(
            f"  ⚡{bus_v:.2f}V  {cur_ma / 1000:.3f}A  {pwr_w:.2f}W  🔋{bat_pct:.0f}%",
            True, (70, 215, 100),
        )
        screen.blit(pw, (SEN_X1, hud_y + 6))

        # Status strip — mode shown with its colour
        st_base = fonts["sm"].render(
            f"  Spd:{motor_speed}  T:{cpu_temp}  CPU:{cpu:.0f}%  "
            f"RAM:{ram:.0f}%  IP:{local_ip}  "
            f"Inf:{'ON' if inference_on else 'off'}  Mus:{music_sym}  Mode:",
            True, (160, 190, 235),
        )
        screen.blit(st_base, (SEN_X1, hud_y + 24))
        mode_surf = fonts["sm"].render(f" [{mode_label}]", True, mode_color)
        screen.blit(mode_surf, (SEN_X1 + st_base.get_width(), hud_y + 24))

        # Mode hint line
        hint = fonts["xs"].render(
            "  1=KEYBOARD  2=IR REMOTE  3=AUTONOMOUS  4=IDLE (stop all)",
            True, (80, 100, 140),
        )
        screen.blit(hint, (SEN_X1, hud_y + 42))

        # Sensor grid — 2 columns
        mid = (len(SENSOR_ROWS) + 1) // 2
        for i, ((attr, _), lbl_surf) in enumerate(zip(SENSOR_ROWS, lbl_surfaces)):
            col = 0 if i < mid else 1
            row = i if i < mid else i - mid
            x   = SEN_X1 + col * (SEN_X2 - SEN_X1)
            y   = SEN_TOP + row * 19
            screen.blit(lbl_surf, (x, y))
            val_s = fonts["xs"].render(
                str(getattr(state, attr, "—")), True, (215, 230, 255)
            )
            screen.blit(val_s, (x + 88, y))

        # Button panel
        draw_panel(screen, btn_panel_rect, fill=(10, 14, 26), alpha=230,
                   border=(42, 62, 100), radius=6)
        screen.blit(
            fonts["hd"].render("CONTROLS", True, (100, 150, 210)),
            (btn_panel_x, hud_y + 8),
        )
        btn_cols   = 2
        btn_margin = 6
        bx0        = btn_panel_x + 4
        by0        = hud_y + 34
        btn_w      = (btn_panel_rect.width - btn_margin * (btn_cols + 1)) // btn_cols

        for idx, button in enumerate(buttons):
            col = idx % btn_cols
            row = idx // btn_cols
            button.rect.x     = bx0 + col * (btn_w + btn_margin)
            button.rect.y     = by0 + row * (button.rect.height + btn_margin)
            button.rect.width = btn_w
            if hasattr(button, "label") and button.label in ("Play", "▶", "Play Music"):
                button.enabled = not music_on
            button.draw(screen)

        # IDLE blackout overlay (drawn last so it covers everything)
        if mode_manager.is_idle():
            _draw_idle_overlay(screen, fonts)

        pygame.display.flip()
        clock.tick(30)

        # ════════════════════════════════
        #  EVENTS
        # ════════════════════════════════
        for event in pygame.event.get():

            if event.type == pygame.QUIT:
                running = False

            # Music track-end (intercept to respect music_blocked)
            if hasattr(music, "MUSIC_END_EVENT") and event.type == music.MUSIC_END_EVENT:
                if not music_blocked:
                    music.play_next_track()
                continue

            music.handle_music_event(event)

            # ── Keyboard ──
            if event.type == pygame.KEYDOWN:
                k = event.key

                # ── Mode select — always available ──
                if k == pygame.K_1:
                    register_on_mode_change(universal_mode_change)
                    mode_manager.set_mode_by_number(1)
                elif k == pygame.K_2:
                    register_on_mode_change(universal_mode_change)
                    mode_manager.set_mode_by_number(2)
                elif k == pygame.K_3:
                    register_on_mode_change(universal_mode_change)
                    mode_manager.set_mode_by_number(3)
                elif k == pygame.K_4:
                    register_on_mode_change(universal_mode_change)
                    mode_manager.set_mode_by_number(4)   # IDLE — always works

                # ── Quit — always available ──
                elif k in (pygame.K_q, pygame.K_ESCAPE):
                    mode_manager.set_mode(DriveMode.IDLE)   # safe stop
                    running = False

                # ── Global controls (work in any non-IDLE mode) ──
                elif k == pygame.K_i:
                    if inference_on:
                        stop_inference()
                        last_frame0 = None
                    else:
                        start_inference()

                elif k == pygame.K_x:
                    motor_speed += config.SPEED_STEP
                    if motor_speed > config.MAX_SPEED:
                        motor_speed = config.MIN_SPEED
                    send_command("dev00", f"SPEED:{motor_speed}")
                    print(f"⚡ Speed: {motor_speed}")

                elif k == pygame.K_SPACE:
                    hard_stop_music()
                    send_command("dev00", "STOP")
                    send_command("dev01", "LIGHT_FRONT_OFF")
                    send_command("dev01", "LIGHT_BACK_ON")
                    print("🛑 STOP")

                elif k == pygame.K_m:
                    music_blocked = False
                    if not music.is_music_playing():
                        music.play_next_track()
                    else:
                        safe_skip()

                elif k == pygame.K_l:
                    leds.toggle_leds()
                elif k == pygame.K_k:
                    leds.toggle_effects()

                elif k == pygame.K_c and char_imgs:
                    char_idx   = (char_idx + 1) % len(char_imgs)
                    char_image = char_imgs[char_idx]

                # ── Movement — KEYBOARD mode only ──
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

            elif event.type == pygame.MOUSEBUTTONDOWN:
                pos = pygame.mouse.get_pos()
                for button in buttons:
                    if button.is_clicked(pos):
                        is_play = (
                            hasattr(button, "label")
                            and button.label in ("Play", "▶", "Play Music")
                        )
                        if is_play:
                            if music.is_music_playing():
                                continue
                            music_blocked = False
                        button.action()

    # ════════════════════════════════
    #  CLEANUP
    # ════════════════════════════════
    print("🧹 Cleaning up…")
    cam0_stop_event.set()
    for cam in (picam2, picam2_ai):
        if cam:
            try:
                cam.stop()
                cam.close()
            except Exception:
                pass
    pygame.quit()
    GPIO.cleanup()
    print("✅ Done")