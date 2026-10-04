import pygame
import time
import os
import threading
import config
import leds
from buttons import create_buttons
import state
from arduino import send_command
from stats import get_cpu_temp, get_system_stats, get_local_ip
from camera_actions import check_recording_timeout
import music
from ina219_module import INA219
import RPi.GPIO as GPIO
from picamera2 import Picamera2
import platform
import json
from queue import Queue
import state_machine
from camera_thread import camera_loop
# from celebration import celebration_routine

# ========== Global Setup ==========
motor_speed = config.DEFAULT_SPEED
pressed_keys = set()
frame_queue = Queue(maxsize=1)
celebration_active = False
celebration_lock = threading.Lock()
BUTTON_SPACING = 10

pygame.font.init()
font = pygame.font.Font(None, 30)

time.sleep(3)
pygame.mixer.init()
pygame.mixer.music.load("./audio/startup.mp3")
pygame.mixer.music.play()

with open('./config.json') as json_file:
    config_data = json.load(json_file)

app_name = config_data.get('Config', {}).get('AppName', 'default_app')
print(f"App Name: {app_name}")

while pygame.mixer.music.get_busy():
    pygame.time.Clock().tick(10)

PYTHON_CMD = "python" if platform.system() == "Windows" else "python3"

# ========== Main UI ==========
def run_ui(model=None, mode="cam", task="detect"):
    global motor_speed, pressed_keys, celebration_active

    pygame.init()
    screen = pygame.display.set_mode(config.SCREEN_SIZE)
    pygame.display.set_caption("KIDA")
    try:  # window icon: the robot's avatar
        pygame.display.set_icon(pygame.image.load(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "images", "kida01-icon.png")))
    except (pygame.error, OSError):
        pass

    # Initialize hardware
    ina219_module = INA219(addr=0x41)
    leds.setup_leds()
    leds.startup_led_fade()
    send_command("dev00", "RAINBOW")
    music.init_music()

    # Load character images, KIDA's avatar first
    avatar_path = os.path.join(os.path.dirname(config.CHARACTER_FOLDER), "kida_avatar.jpeg")
    character_images = [
        pygame.transform.scale(pygame.image.load(p), config.IMAGE_SIZE)
        for p in ([avatar_path] if os.path.isfile(avatar_path) else []) + [
            os.path.join(config.CHARACTER_FOLDER, f)
            for f in sorted(os.listdir(config.CHARACTER_FOLDER))
            if f.lower().endswith((".jpg", ".jpeg", ".png"))
        ]
    ]

    # Load background
    background = pygame.image.load(config.BACKGROUND_IMAGE)
    background = pygame.transform.scale(background, config.SCREEN_SIZE)
    background.set_alpha(32)

    char_index = 0
    char_image = character_images[char_index] if character_images else None
    buttons = create_buttons()

    # Camera & inference setup
    picam2 = None
    inference_enabled = False
    last_camera_frame = None

    if mode == "cam":
        try:
            picam2 = Picamera2()
            config_cam = picam2.create_preview_configuration(
                main={"format": "RGB888", "size": (640, 480)}
            )
            picam2.configure(config_cam)
            picam2.start()
            print("✅ Camera initialized successfully")
        except Exception as e:
            print(f"❌ Camera init failed: {e}")
            picam2 = None

    def start_camera_thread():
        if picam2 and model and inference_enabled:
            threading.Thread(
                target=camera_loop, args=(picam2, model, task, frame_queue), daemon=True
            ).start()
            print("✅ Camera thread started with inference ON")

    # Main loop
    clock = pygame.time.Clock()
    running = True
    last_stats_update = 0
    stats_update_interval = 1.5
    cpu, ram, cpu_temp = 0, 0, "N/A"
    bus_voltage, current, power, percent = 0, 0, 0, 0
    small_font = pygame.font.SysFont(None, 24)

    # Force keyboard control for testing
    state_machine.keyboard_control = True
    print(f"🎮 Keyboard control: {state_machine.keyboard_control}")
    print(f"🏁 Starting motor speed: {motor_speed}")
    print(f"🧠 Inference enabled: {inference_enabled} (Press 'i' to toggle)")

    while running:
        current_time = time.time()
        check_recording_timeout()

        # Update system stats
        if current_time - last_stats_update > stats_update_interval:
            cpu_temp = get_cpu_temp()
            cpu, ram = get_system_stats()
            try:
                bus_voltage = ina219_module.getBusVoltage_V()
                current = ina219_module.getCurrent_mA()
                power = ina219_module.getPower_W()
                percent = max(0, min(100, (bus_voltage - 9) / 3.6 * 100))
            except Exception as e:
                print(f"Power monitoring error: {e}")
                bus_voltage = current = power = percent = 0
            last_stats_update = current_time

        # Display texts
        local_ip = get_local_ip()
        mode_str = "Keyboard" if state_machine.keyboard_control else "Autonomous"

        sensor_text = (
            f"Voltage: {bus_voltage:.2f} V  "
            f"Current: {current/1000:.3f} A  "
            f"Power: {power:.2f} W  "
            f"Battery: {percent:.1f}%"
        )

        arduino_attrs = [
            "photoValue","uvValue","metalValue","ballSwitchValue","motionValue",
            "lfLeftValue","lfMidValue","lfRightValue","laserValue","ultrasonic0Value","ultrasonic1Value",
            "servoPosValue","buttonValue","motorSpeedValue","systemStatus",
        ]
        arduino_texts = [str(getattr(state, attr, f"{attr.upper()}: N/A")) for attr in arduino_attrs]
        arduino_line = "   ".join(arduino_texts)

        status_text = (
            f"Mode: {mode_str}   Speed: {motor_speed}   Temp: {cpu_temp}   "
            f"CPU: {cpu:.1f}%   RAM: {ram:.1f}%   IP: {local_ip}   "
            f"Keys: {len(pressed_keys)}   Inference: {'ON' if inference_enabled else 'OFF'}"
        )

        # Render surfaces
        cached_sensor_surface = small_font.render(sensor_text, True, (0, 255, 0))
        cached_arduino_surface = small_font.render(arduino_line, True, (255, 255, 255))
        cached_status_surface = small_font.render(status_text, True, (255, 255, 255))

        # Draw everything
        screen.blit(background, (0, 0))
        if char_image:
            screen.blit(char_image, (20, 20))
        screen.blit(cached_sensor_surface, (20, 410))
        screen.blit(cached_arduino_surface, (20, 435))
        screen.blit(cached_status_surface, (20, 460))

        # Camera display
        if not frame_queue.empty():
            try:
                last_camera_frame = frame_queue.get_nowait()
            except:
                pass

        if last_camera_frame is not None:
            try:
                frame_surface = pygame.surfarray.make_surface(last_camera_frame.swapaxes(0, 1))
                camera_rect = pygame.Rect(450, 20, 280, 210)
                frame_surface = pygame.transform.scale(frame_surface, camera_rect.size)
                screen.blit(frame_surface, camera_rect.topleft)
            except Exception as e:
                print(f"Camera display error: {e}")

        # Draw buttons
        for idx, button in enumerate(buttons):
            button.rect.x = 750
            button.rect.y = 20 + idx * (button.rect.height + 10)
            button.draw(screen)

        pygame.display.flip()
        clock.tick(30)

        # ========== Event Handling ==========
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                print("🛑 Quit event received")
                running = False

            music.handle_music_event(event)

            # KEYDOWN
            if event.type == pygame.KEYDOWN:
                key = event.key
                # key_name = pygame.key.name(key)

                # Toggle inference
                if key == pygame.K_i:
                    inference_enabled = not inference_enabled
                    print(f"🧠 Inference toggled to: {'ON' if inference_enabled else 'OFF'}")
                    if inference_enabled:
                        start_camera_thread()
                    else:
                        with frame_queue.mutex:
                            frame_queue.queue.clear()
                        last_camera_frame = None

                # Speed adjustment
                elif key == pygame.K_x:
                    motor_speed += config.SPEED_STEP
                    if motor_speed > config.MAX_SPEED:
                        motor_speed = config.MIN_SPEED
                    print(f"⚡ Speed changed to: {motor_speed}")
                    send_command("dev00", f"SPEED:{motor_speed}")

                # Movement keys
                elif key in [pygame.K_w, pygame.K_s, pygame.K_a, pygame.K_d] and state_machine.keyboard_control:
                    moves = {pygame.K_w: "FORWARD", pygame.K_s: "BACKWARD", pygame.K_a: "LEFT", pygame.K_d: "RIGHT"}
                    print(f"🚗 Moving {moves[key]}")
                    send_command("dev00", moves[key])
                    send_command("dev00", "RAINBOW")
                    send_command("dev01", "LIGHT_FRONT_ON")
                    send_command("dev01", "LIGHT_BACK_OFF")
                    leds.toggle_leds()
                    pressed_keys.add(key)

                # Other controls
                elif key == pygame.K_SPACE:
                    if music.is_music_playing():
                        music.stop_music()
                    if state_machine.keyboard_control:
                        send_command("dev00", "CYCLE")
                        send_command("dev01", "LIGHT_FRONT_OFF")
                        send_command("dev01", "LIGHT_BACK_ON")
                elif key == pygame.K_q:
                    print("🛑 Q pressed - shutting down")
                    send_command("dev00", "STOP")
                    send_command("dev01", "LIGHT_FRONT_OFF")
                    send_command("dev01", "LIGHT_BACK_ON")
                    running = False
                elif key == pygame.K_m:
                    if not music.is_music_playing():
                        music.play_next_track()
                    else:
                        music.skip_music()
                elif key == pygame.K_l:
                    leds.toggle_leds()
                elif key == pygame.K_k:
                    leds.toggle_effects()
                elif key == pygame.K_t:
                    state_machine.keyboard_control = not state_machine.keyboard_control
                    send_command("dev00", "STOP")
                    send_command("dev01", "LIGHT_FRONT_OFF")
                    send_command("dev01", "LIGHT_BACK_ON")
                    print(f"🎮 Keyboard control now: {state_machine.keyboard_control}")

            # KEYUP
            elif event.type == pygame.KEYUP:
                key = event.key
                if state_machine.keyboard_control and key in pressed_keys:
                    print(f"🛑 Stopping motor (key released)")
                    send_command("dev00", "STOP")
                    send_command("dev01", "LIGHT_FRONT_OFF")
                    send_command("dev01", "LIGHT_BACK_ON")
                    pressed_keys.discard(key)

            # MOUSE
            elif event.type == pygame.MOUSEBUTTONDOWN:
                pos = pygame.mouse.get_pos()
                for button in buttons:
                    if button.is_clicked(pos):
                        button.action()

    # CLEANUP
    print("🧹 Cleaning up...")
    if picam2:
        try:
            picam2.stop()
            picam2.close()
        except:
            pass
    pygame.quit()
    GPIO.cleanup()
    print("✅ Cleanup complete")
