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
#   I        — toggle YOLO inference on cam-0 (cam-1 always uses IMX500 on-chip)
#   X        — cycle motor speed
#   M        — play / skip music
#   L        — toggle LEDs
#   K        — toggle LED effects
#   U        — lock motors instantly / open password prompt to unlock
#   C        — take a photo
#   V        — record a video
#   Q        — quit for good (process exits, run.sh will not restart it)
#   ESC      — close the UI (run.sh restarts it after a few seconds)
#
# Gamepad plugged into the Pi (USB / Logitech wireless dongle) — KEYBOARD mode:
#   left stick — drive (analog)   right stick — aim servo   A/trigger — photo
#   B — stop    X/Y — speed −/+   LB/RB — prev/next mode    RT — video
#   Start — lock / unlock prompt  Back — LIDAR sweep
#   Rumbles on tipping, vibration, or an obstacle while driving (haptics.py)
#   (see joystick_drive.py; a pad plugged into the PC is read by the
#    controller / website instead)

import sys, os, json, time, threading, platform
# The Pi's own gamepad must keep working even if the HUD window loses
# focus (SDL drops joystick input for unfocused windows by default).
os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")
import pygame
import config
import leds
import mode_manager
import state
import camera_memory

# music.py deleted — MusicPlayer is the sole music interface
from music_player import MusicPlayer

from state import DriveMode
from buttons import create_buttons
from arduino import send_command, start_arduino_threads
from mpu6050_module import start_mpu_thread
from stats import get_cpu_temp, get_system_stats, get_local_ip
import camera_actions
from camera_actions import check_recording_timeout
from ina219_module import INA219
from picamera2 import Picamera2
from queue import Empty
import RPi.GPIO as GPIO

# ── Refactored sub-modules ──
import ir_bridge
import hud_draw
import hud_layout
import event_handler
import motor_lock
from button_widget import Button
from password_prompt import PasswordPrompt
from text_prompt import TextPrompt
from camera_threads import (frame_queue, frame_queue2,
                             start_cam0, stop_cam0)
from imx500_cam1 import create_imx500_camera, start_imx500_cam1, stop_imx500_cam1
from mode_control import init_mode_control
from joystick_drive import JoystickDrive, LocalActions

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
#  Layout — geometry + sensor rows live in hud_layout.py, shared with
#  controller/main.py so both HUDs stay visually identical.
# ─────────────────────────────────────────────
SENSOR_ROWS = hud_layout.SENSOR_ROWS

# ─────────────────────────────────────────────
#  Celebration (TODO: move to emotions.py)
# ─────────────────────────────────────────────
_celebration_lock   = threading.Lock()
_celebration_active = False


def celebration_routine(music_ctrl: MusicPlayer):
    global _celebration_active
    print("🎉 Celebration!")
    threading.Thread(target=leds.run_chase_effect, daemon=True).start()
    music_ctrl.play_next()
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

    # ── Layout (shared with controller/main.py via hud_layout.py) ──
    layout = hud_layout.compute_layout(SW, SH)
    FACE_RECT      = layout["face_rect"]
    CAM1_RECT      = layout["cam1_rect"]
    CAM0_RECT      = layout["cam0_rect"]
    PHOTO_RECT     = layout["photo_rect"]
    HUD_RECT       = layout["hud_rect"]
    hud_y          = layout["hud_y"]
    hud_h          = layout["hud_h"]
    SEN_X1         = layout["sen_x1"]
    SEN_X2         = layout["sen_x2"]
    SEN_TOP        = layout["sen_top"]
    btn_panel_x    = layout["btn_panel_x"]
    btn_panel_rect = layout["btn_panel_rect"]

    # ── Hardware ──
    ina219_module = None
    try:
        ina219_module = INA219(addr=0x41)
    except Exception as e:
        print(f"⚠️ INA219: {e}")

    leds.setup_leds()
    leds.startup_led_fade()

    # ── Music player (replaces music.init_music()) ──────────────────────────
    music_ctrl = MusicPlayer()   # reads config.MUSIC_FOLDER + config.SUPPORTED_FORMATS

    # Register with web bridge so Flask action routes can control playback
    try:
        import web_bridge
        web_bridge.register_music(music_ctrl)
    except Exception as e:
        print(f"⚠️ web_bridge music: {e}")

    # Start sensor-assisted driving (background safety thread)
    try:
        import sensor_assist
        sensor_assist.start()
    except Exception as e:
        print(f"⚠️ sensor_assist: {e}")

    # ── Assets ──
    # Character face — 1:1 panel (FACE_RECT). Starts on KIDA002.jpeg if
    # present; 'C' still cycles through every image in the characters folder.
    char_filenames = sorted(
        f for f in os.listdir(config.CHARACTER_FOLDER)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    )
    char_imgs = [
        pygame.transform.smoothscale(
            pygame.image.load(os.path.join(config.CHARACTER_FOLDER, fname)).convert_alpha(),
            FACE_RECT.size,
        )
        for fname in char_filenames
    ]
    char_idx = next(
        (i for i, f in enumerate(char_filenames) if f.lower() == "kida002.jpeg"),
        0,
    )
    char_image = char_imgs[char_idx] if char_imgs else None

    bg = pygame.image.load(config.BACKGROUND_IMAGE).convert()
    bg = pygame.transform.smoothscale(bg, (SW, SH))
    bg.set_alpha(28)

    buttons      = create_buttons(music_ctrl)
    lbl_surfaces = [
        fonts["xs"].render(f"{lbl}:", True, (100, 130, 185))
        for _, lbl in SENSOR_ROWS
    ]

    # ── Motor lock, drive scheme toggle, typed-message box — all three
    #    used to float at fixed top-left coordinates, which overlapped the
    #    face camera panel (hud_layout.compute_layout puts face_rect at
    #    roughly (12, 12) sized up to 40% of screen height). Now folded
    #    into the auto-arranged button grid instead — hud_draw.py's
    #    draw_button_panel() special-cases their labels each frame
    #    (matching the existing "Cam:"/"Play" pattern) to keep them live.
    lock_prompt = PasswordPrompt("ENTER PASSWORD TO UNLOCK MOTORS")

    def _motor_lock_click():
        if motor_lock.is_locked():
            lock_prompt.open(lambda pw: motor_lock.try_unlock(pw))
        else:
            motor_lock.lock()

    lock_btn = Button((0, 0, 160, 36), (140, 200, 140), "Lock Motors", _motor_lock_click)

    # Drive scheme toggle — WASD (differential) vs QAWS (tank, Q/A=left
    # motor, W/S=right motor). Same flag the web HUD and the remote
    # controller flip via state.drive_scheme / the </>/,. keys.
    def _drive_scheme_click():
        state.drive_scheme = "QAWS" if state.drive_scheme == "WASD" else "WASD"

    scheme_btn = Button((0, 0, 160, 36), (160, 160, 220), "Scheme: WASD", _drive_scheme_click)

    # Typed message box — bypasses Whisper/wake-word entirely, feeds
    # straight into kida_chat_wakeword's voice_commands→LLM→speak
    # pipeline via submit_text() so it can't race the live voice thread.
    text_prompt = TextPrompt("TYPE A MESSAGE TO KIDA")

    def _text_click():
        try:
            import kida_chat_wakeword
            text_prompt.open(kida_chat_wakeword.submit_text)
        except Exception as e:
            print(f"⚠️ Typed-message box: {e}")

    text_btn = Button((0, 0, 160, 36), (160, 200, 220), "Type to KIDA", _text_click)
    buttons.extend([lock_btn, scheme_btn, text_btn])

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
            camera_actions.set_camera(picam2)
            print("✅ Cam-0 ready")
        except Exception as e:
            print(f"❌ Cam-0: {e}")

        try:
            picam2_ai = create_imx500_camera()
            start_imx500_cam1()
            camera_actions.set_camera(picam2_ai, cam_id=1)
        except Exception as e:
            print(f"❌ Cam-1 IMX500: {e}")

    def toggle_inference():
        nonlocal inference_on, last_frame0
        import state as _state
        if inference_on:
            stop_cam0()
            inference_on = False
            _state.inference_on = False
            last_frame0  = None
        else:
            if picam2:
                start_cam0(picam2, model, task)
                inference_on = True
                _state.inference_on = True

    # Register with web bridge so /action (dashboard + remote controller)
    # can flip inference the same way the local 'I' key does.
    try:
        import web_bridge
        web_bridge.register_inference_toggle(toggle_inference)
    except Exception as e:
        print(f"⚠️ web_bridge inference toggle: {e}")

    # ── Main loop vars ──
    clock           = pygame.time.Clock()
    running         = True
    hard_quit       = False
    last_stats_time = 0
    STATS_INTERVAL  = 2.0
    last_heartbeat_time = 0
    HEARTBEAT_INTERVAL = 0.5   # well under the Arduino's AUTONOMOUS_WATCHDOG_MS (1.5s)
    cpu = ram = 0
    cpu_temp = "N/A"
    bus_v = cur_ma = pwr_w = bat_pct = 0.0
    motor_speed_box       = [motor_speed]   # mutable ref for ir_bridge
    last_photo_surf       = None
    last_photo_path_seen  = None

    mode_manager.set_mode(DriveMode.KEYBOARD, stop_motors=False)
    joystick = JoystickDrive(LocalActions(), on_unlock_request=_motor_lock_click)
    print("🎮 Keys: 1=KB 2=IR 3=AUTO 4=IDLE | I=infer | M=music | U=lock/unlock | SPC=stop | ESC=close Q=quit for good")

    # ═══════════════════════════════════════════
    #  MAIN LOOP
    # ═══════════════════════════════════════════
    import web_bridge as _web_bridge

    while running:
        now = time.time()
        check_recording_timeout()
        _web_bridge.check_web_drive_timeout()

        ir_bridge.poll(motor_speed_box, music_ctrl=music_ctrl)
        motor_speed = motor_speed_box[0]

        # ── Autonomous heartbeat — tells the Arduino's watchdog the Pi is
        # still alive, so it doesn't need one to keep driving after a crash ──
        if mode_manager.is_autonomous() and now - last_heartbeat_time > HEARTBEAT_INTERVAL:
            send_command("dev00", "PING")
            last_heartbeat_time = now

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
                    import state as _state
                    _state.bus_v   = bus_v
                    _state.cur_ma  = cur_ma
                    _state.pwr_w   = pwr_w
                    _state.bat_pct = bat_pct
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

        # ── Refresh "last photo" panel if a new photo was taken ──
        photo_path, _ = camera_memory.get_last_photo()
        if photo_path != last_photo_path_seen:
            last_photo_path_seen = photo_path
            last_photo_surf = None
            if photo_path and os.path.isfile(photo_path):
                try:
                    img = pygame.image.load(photo_path).convert()
                    last_photo_surf = pygame.transform.smoothscale(img, PHOTO_RECT.size)
                except Exception as e:
                    print(f"⚠️ last photo load: {e}")

        # ════════════════════════════════
        #  RENDER
        # ════════════════════════════════
        screen.fill((7, 9, 16))
        screen.blit(bg, (0, 0))

        hud_draw.draw_static_panel(screen, char_image, FACE_RECT,
                                   "KIDA", fonts["xs"], fonts["nosig"])
        hud_draw.draw_camera_panel(screen, last_frame1, CAM1_RECT,
                                   "Cam 1", fonts["xs"], fonts["nosig"])
        hud_draw.draw_camera_panel(screen, last_frame0, CAM0_RECT,
                                   "Cam 0",   fonts["xs"], fonts["nosig"])
        hud_draw.draw_static_panel(screen, last_photo_surf, PHOTO_RECT,
                                   "Last Photo Taken", fonts["xs"], fonts["nosig"])

        hud_draw.draw_panel(screen, HUD_RECT, fill=(7, 11, 20), alpha=218,
                            border=(32, 52, 88), radius=0)

        hud_draw.draw_status_strip(
            screen, fonts, hud_y, SEN_X1,
            motor_speed, cpu_temp, cpu, ram, get_local_ip(),
            inference_on, bus_v, cur_ma, pwr_w, bat_pct,
            music_ctrl.is_playing(),
        )
        hud_draw.draw_sensor_grid(
            screen, fonts, SENSOR_ROWS, lbl_surfaces,
            SEN_X1, SEN_X2, SEN_TOP,
        )
        hud_draw.draw_button_panel(
            screen, fonts, buttons, hud_y, btn_panel_x, btn_panel_rect,
            music_ctrl.is_playing(),
        )

        if mode_manager.is_idle():
            hud_draw.draw_idle_overlay(screen, fonts)

        lock_prompt.draw(screen, fonts)
        text_prompt.draw(screen, fonts)

        pygame.display.flip()
        clock.tick(30)

        # ════════════════════════════════
        #  EVENTS
        # ════════════════════════════════
        raw_events = pygame.event.get()

        # Gamepad first, so releasing the stick still stops the robot even
        # while a prompt below is swallowing input.
        joystick.handle_events(raw_events)

        # Speed can change outside this loop (gamepad X/Y, web, remote
        # controller) — follow it so X and the HUD start from the real value.
        if isinstance(state.motorSpeedValue, int):
            motor_speed = motor_speed_box[0] = state.motorSpeedValue

        # While a prompt is open, every key goes to it — nothing else (mode
        # switches, drive keys, buttons) should fire mid-entry.
        if lock_prompt.active:
            for event in raw_events:
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    lock_prompt.handle_key(event)
            continue

        if text_prompt.active:
            for event in raw_events:
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    text_prompt.handle_key(event)
            continue

        # Let MusicPlayer handle its own SONG_END auto-advance event
        for event in raw_events:
            music_ctrl.handle_event(event)

        sigs = event_handler.handle_events(
            raw_events, buttons, pressed_keys,
            motor_speed, inference_on,
            music_ctrl,
            lock_prompt=lock_prompt,
        )

        if sigs["quit"]:
            running = False
            hard_quit = sigs["hard_quit"]

        if sigs["inference_toggle"]:
            toggle_inference()
        motor_speed         = sigs["motor_speed"]
        motor_speed_box[0]  = motor_speed

    # ════════════════════════════════
    #  CLEANUP
    # ════════════════════════════════
    print("🧹 Cleaning up…")
    joystick.stop()
    music_ctrl.stop()
    # Must happen before cam.stop()/cam.close() below — stopping the camera
    # while the H264Encoder still has an active recording leaves its
    # background encoder thread blocked waiting on frames that stop
    # arriving, which hangs shutdown. stop_recording() joins that thread
    # cleanly first.
    if camera_actions.recording:
        camera_actions.stop_video()
    stop_cam0()
    stop_imx500_cam1()
    for cam in (picam2, picam2_ai):
        if cam:
            try:
                cam.stop(); cam.close()
            except Exception:
                pass
    pygame.quit()
    GPIO.cleanup()
    print("✅ Done")
    return hard_quit