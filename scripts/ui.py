# ui.py — KIDA main UI  (refactored)
#
# Drive modes (keys 1-4, always available):
#   1 → KEYBOARD    WASD to drive
#   2 → IR_REMOTE   IR handset drives
#   3 → AUTONOMOUS  Arduino obstacle-avoidance loop  ← AUTO_ON/OFF fixed
#   4 → IDLE        all motors stop
#
# Other keys:
#   W/A/S/D  — move          (KEYBOARD mode only)
#   SPACE    — hard stop motors + music
#   I        — toggle YOLO inference on cam-0
#   X        — cycle motor speed
#   M        — play / skip music
#   L        — toggle LEDs
#   K        — toggle LED effects
#   C        — cycle character avatar
#   Q / ESC  — quit

import sys, os, json, time, threading, platform
import pygame
import config
import leds
import music
import mode_manager

from state import DriveMode
from buttons import create_buttons
from arduino import send_command, start_arduino_threads
from mpu6050_module import start_mpu_thread
from stats import get_cpu_temp, get_system_stats, get_local_ip
from camera_actions import check_recording_timeout
from ina219_module import INA219
from picamera2 import Picamera2
from queue import Empty
import RPi.GPIO as GPIO

# ── Refactored sub-modules ──
import music_ctrl
import ir_bridge
import hud_draw
import event_handler
from camera_threads import (frame_queue, frame_queue2,
                             start_cam0, start_cam1, stop_cam0)
from mode_control import init_mode_control

# ─────────────────────────────────────────────
#  Startup (runs at import time)
# ─────────────────────────────────────────────
with open("./config.json") as f:
    _cfg = json.load(f)

BASE_DIR   = os.path.abspath(os.path.dirname(__file__))
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
CAM_H_FRAC = 0.56

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
#  Celebration (TODO: move to emotions.py)
# ─────────────────────────────────────────────
_celebration_lock   = threading.Lock()
_celebration_active = False


def celebration_routine():
    global _celebration_active
    print("🎉 Celebration!")
    threading.Thread(target=leds.run_chase_effect, daemon=True).start()
    music_ctrl.safe_play_next()
    send_command("dev00", "HAPPY")
    time.sleep(15)
    with _celebration_lock:
        _celebration_active = False


# ─────────────────────────────────────────────
#  Main UI entry point
# ─────────────────────────────────────────────
def run_ui(model=None, mode="cam", task="detect", tracker_path=None):
    motor_speed  = config.DEFAULT_SPEED
    pressed_keys = set()

    pygame.init()

    # ── Register mode-change hook (AUTO_ON/OFF lives here) ──
    init_mode_control()

    # ── Background services ──
    for label, fn in (("Arduino threads", start_arduino_threads),
                      ("MPU thread",      start_mpu_thread)):
        try:
            fn()
        except Exception as e:
            print(f"⚠️ {label}: {e}")

    # ── Display ──
    info   = pygame.display.Info()
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

    buttons      = create_buttons()
    lbl_surfaces = [
        fonts["xs"].render(f"{lbl}:", True, (100, 130, 185))
        for _, lbl in SENSOR_ROWS
    ]

    # ── Cameras ──
    picam2      = None
    picam2_ai   = None
    inference_on  = False
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
            start_cam1(picam2_ai)
            print("✅ Cam-1 ready")
        except Exception as e:
            print(f"❌ Cam-1: {e}")

    def toggle_inference():
        nonlocal inference_on, last_frame0
        if inference_on:
            stop_cam0()
            inference_on = False
            last_frame0  = None
        else:
            if picam2:
                start_cam0(picam2, model, task)
                inference_on = True

    # ── Main loop vars ──
    clock           = pygame.time.Clock()
    running         = True
    last_stats_time = 0
    STATS_INTERVAL  = 2.0
    cpu = ram = 0
    cpu_temp = "N/A"
    bus_v = cur_ma = pwr_w = bat_pct = 0.0
    motor_speed_box = [motor_speed]   # mutable ref for ir_bridge

    mode_manager.set_mode(DriveMode.KEYBOARD, stop_motors=False)
    print("🎮 Keys: 1=KB 2=IR 3=AUTO 4=IDLE | I=infer | M=music | SPC=stop | Q=quit")

    # ═══════════════════════════════════════════
    #  MAIN LOOP
    # ═══════════════════════════════════════════
    while running:
        now = time.time()
        check_recording_timeout()

        ir_bridge.poll(motor_speed_box)
        motor_speed = motor_speed_box[0]

        # ── Stats (throttled) ──
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

        hud_draw.draw_camera_panel(screen, last_frame1, CAM1_RECT,
                                   "SLOT 1 — AI CAM", fonts["xs"], fonts["nosig"])
        hud_draw.draw_camera_panel(screen, last_frame0, CAM0_RECT,
                                   "SLOT 0 — MAIN",   fonts["xs"], fonts["nosig"])

        if char_image:
            screen.blit(char_image, (CAM_PAD, hud_y - 84))

        hud_draw.draw_panel(screen, HUD_RECT, fill=(7, 11, 20), alpha=218,
                            border=(32, 52, 88), radius=0)

        from stats import get_local_ip as _ip
        hud_draw.draw_status_strip(
            screen, fonts, hud_y, SEN_X1,
            motor_speed, cpu_temp, cpu, ram, _ip(),
            inference_on, bus_v, cur_ma, pwr_w, bat_pct,
        )
        hud_draw.draw_sensor_grid(
            screen, fonts, SENSOR_ROWS, lbl_surfaces,
            SEN_X1, SEN_X2, SEN_TOP,
        )
        hud_draw.draw_button_panel(
            screen, fonts, buttons, hud_y, btn_panel_x, btn_panel_rect,
        )

        if mode_manager.is_idle():
            hud_draw.draw_idle_overlay(screen, fonts)

        pygame.display.flip()
        clock.tick(30)

        # ════════════════════════════════
        #  EVENTS
        # ════════════════════════════════
        sigs = event_handler.handle_events(
            pygame.event.get(),
            buttons, pressed_keys,
            motor_speed, inference_on,
            char_imgs, char_idx,
        )

        if sigs["quit"]:
            running = False
        if sigs["inference_toggle"]:
            toggle_inference()
        if sigs["char_next"] and char_imgs:
            char_idx   = (char_idx + 1) % len(char_imgs)
            char_image = char_imgs[char_idx]
        motor_speed         = sigs["motor_speed"]
        motor_speed_box[0]  = motor_speed

    # ════════════════════════════════
    #  CLEANUP
    # ════════════════════════════════
    print("🧹 Cleaning up…")
    stop_cam0()
    for cam in (picam2, picam2_ai):
        if cam:
            try:
                cam.stop(); cam.close()
            except Exception:
                pass
    pygame.quit()
    GPIO.cleanup()
    print("✅ Done")
