import cv2
import numpy as np
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
#from memory.system_memory import SystemMemory
#from memory.user_memory import UserMemory
#from memory.world_memory import WorldMemory
#from memory.personality_memory import PersonalityMemory
import time

#system = SystemMemory()
#user = UserMemory()
#world = WorldMemory()
#personality = PersonalityMemory()

motor_speed = config.DEFAULT_SPEED
keyboard_control = False
pressed_keys = set()

pygame.font.init()
font = pygame.font.Font(None, 30)

# Track last detection time and celebration state
last_person_detected_time = 0
celebration_active = False
celebration_lock = threading.Lock()
celebration_duration = 15  # seconds

time.sleep(3)
waitTime = 5.0

# Initialize pygame mixer
pygame.mixer.init()

# Load and play the startup sound
pygame.mixer.music.load("./audio/startup.mp3")
pygame.mixer.music.play()

global current_script_dir
with open('./config.json') as json_file:
    config_data = json.load(json_file)

app_name = config_data.get('Config', {}).get('AppName', 'default_app')
print(app_name)
#print(f"KIDA mood: {personality.get_mood()}")
#print("System Memory:", system.data)
#print("User Memory:", user.data)
#print("World Memory:", world.data)
#print("Personality Memory:", personality.data)

# Wait until the sound finishes playing
while pygame.mixer.music.get_busy():
    pygame.time.Clock().tick(10)

# === Voice Commands Map ===
if platform.system() == "Windows":
    PYTHON_CMD = "python"
else:
    PYTHON_CMD = "python3"

def celebration_routine():
    global celebration_active
    print("🎉 Celebration started!")

    # Start run_chase_effect in a separate thread to avoid blocking main UI loop
    threading.Thread(target=leds.run_chase_effect, daemon=True).start()

    music.play_next_track()
    send_command("dev0", "HAPPY")

    # Wait for celebration duration (or you could join the above thread if you want)
    time.sleep(celebration_duration)

    print("✅ Celebration ended")
    with celebration_lock:
        celebration_active = False

def run_ui(model=None, mode="cam", task="detect", tracker_path=None):



    global motor_speed, last_person_detected_time, celebration_active

    pygame.init()
    screen = pygame.display.set_mode(config.SCREEN_SIZE)
    pygame.display.set_caption("KIDA")

    ina219_module = INA219(addr=0x41)
    leds.setup_leds()
    leds.startup_led_fade()
    music.init_music()

    # Load UI assets
    character_images = [
        pygame.transform.scale(
            pygame.image.load(os.path.join(config.CHARACTER_FOLDER, f)),
            config.IMAGE_SIZE,
        )
        for f in os.listdir(config.CHARACTER_FOLDER)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    ]
    background = pygame.image.load(config.BACKGROUND_IMAGE)
    background = pygame.transform.scale(background, config.SCREEN_SIZE)
    background.set_alpha(32)

    char_index = 0
    char_image = character_images[char_index]
    buttons = create_buttons()

    # Setup PiCamera2 if YOLO is enabled
    picam2 = None
    if model and mode == "cam":
        try:
            picam2 = Picamera2()
            config_cam = picam2.create_preview_configuration(
                main={"format": "RGB888", "size": (640, 480)}
            )
            picam2.configure(config_cam)
            picam2.start()
        except Exception as e:
            print(f"Camera init failed: {e}")
            picam2 = None

    clock = pygame.time.Clock()
    running = True
    last_stats_update = 0
    stats_update_interval = 1.5
    cpu, ram, cpu_temp = 0, 0, "N/A"
    bus_voltage, current, power, percent = 0, 0, 0, 0

    small_font = pygame.font.SysFont(None, 24)
    cached_sensor_surface = None
    cached_arduino_surface = None
    cached_status_surface = None
    last_text_update = 0
    text_update_interval = 1.5

    while running:
        current_time = time.time()
        check_recording_timeout()

        # Update stats periodically
        if current_time - last_stats_update > stats_update_interval:
            cpu_temp = get_cpu_temp()
            cpu, ram = get_system_stats()
            bus_voltage = ina219_module.getBusVoltage_V()
            current = ina219_module.getCurrent_mA()
            power = ina219_module.getPower_W()
            percent = (bus_voltage - 9) / 3.6 * 100
            percent = max(0, min(100, percent))
            last_stats_update = current_time

        local_ip = get_local_ip()
        mode_str = "Keyboard" if keyboard_control else "Autonomous"

        # Update text surfaces
        if current_time - last_text_update > text_update_interval:
            sensor_text = (
                f"Voltage: {bus_voltage:.2f} V  "
                f"Current: {current/1000:.3f} A  "
                f"Power: {power:.2f} W  "
                f"Battery: {percent:.1f}%"
            )
            cached_sensor_surface = small_font.render(sensor_text, True, (0, 255, 0))

            arduino_texts = [
                getattr(state, "dev0_photoValue", "Photo: N/A"),
                getattr(state, "dev0_uvValue", "UV: N/A"),
                getattr(state, "dev0_laserValue", "Laser: N/A"),
            ]
            arduino_line = "   ".join(arduino_texts)
            cached_arduino_surface = small_font.render(arduino_line, True, (255, 255, 255))

            status_text = (
                f"Mode: {mode_str}   Speed: {motor_speed}   Temp: {cpu_temp}   "
                f"CPU: {cpu:.1f}%   RAM: {ram:.1f}%   IP: {local_ip}"
            )
            cached_status_surface = small_font.render(status_text, True, (255, 255, 255))
            last_text_update = current_time

        # Draw UI
        screen.blit(background, (0, 0))
        screen.blit(char_image, (20, 20))
        if cached_sensor_surface:
            screen.blit(cached_sensor_surface, (20, 410))
        if cached_arduino_surface:
            screen.blit(cached_arduino_surface, (20, 435))
        if cached_status_surface:
            screen.blit(cached_status_surface, (20, 460))

        # === CAMERA + YOLO ===
        if picam2:
            frame = picam2.capture_array()
            if frame is not None:
                results = model.predict(frame, conf=0.5) if task == "detect" else [frame]
                annotated_frame = results[0].plot() if hasattr(results[0], "plot") else frame

                for r in results:
                    if hasattr(r, "boxes"):
                        for box in r.boxes:
                            cls = model.names[int(box.cls[0])]
                            if cls == "person":
                                print("👤 Person detected!")
                                send_command("dev0", "PERSON_DETECTED")

                                with celebration_lock:
                                    can_celebrate = not celebration_active and (current_time - last_person_detected_time >= 180)

                                if can_celebrate:
                                    with celebration_lock:
                                        celebration_active = True
                                    print("🎉 So happy to see you again after a while!")
                                    threading.Thread(target=celebration_routine, daemon=True).start()

                                last_person_detected_time = current_time

                fps = clock.get_fps()
                cv2.putText(
                    annotated_frame, f"FPS: {fps:.2f}",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1,
                    (0, 255, 0), 2,
                )

                annotated_frame = cv2.cvtColor(annotated_frame, cv2.COLOR_BGR2RGB)
                annotated_frame = cv2.flip(annotated_frame, 1)
                frame_surface = pygame.surfarray.make_surface(annotated_frame.swapaxes(0, 1))
                camera_rect = pygame.Rect(450, 20, 280, 210)
                frame_surface = pygame.transform.scale(frame_surface, camera_rect.size)
                screen.blit(frame_surface, camera_rect.topleft)

        # Draw buttons
        for idx, button in enumerate(buttons):
            button.rect.x = 750
            button.rect.y = 20 + idx * (button.rect.height + 10)
            button.draw(screen)

        pygame.display.flip()
        clock.tick(30)

        # === EVENT HANDLING ===
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            music.handle_music_event(event)

            if event.type == pygame.KEYDOWN:
                key = event.key
                if key == pygame.K_x:
                    motor_speed += config.SPEED_STEP
                    if motor_speed > config.MAX_SPEED:
                        motor_speed = config.MIN_SPEED
                    send_command("dev0", f"SPEED:{motor_speed}")

                elif key == pygame.K_w and keyboard_control:
                    send_command("dev0", "FORWARD")
                    pressed_keys.add("w")
                elif key == pygame.K_s and keyboard_control:
                    send_command("dev0", "BACKWARD")
                    pressed_keys.add("s")
                elif key == pygame.K_a and keyboard_control:
                    send_command("dev0", "LEFT")
                    pressed_keys.add("a")
                elif key == pygame.K_d and keyboard_control:
                    send_command("dev0", "RIGHT")
                    pressed_keys.add("d")
                elif key == pygame.K_SPACE:
                    if music.is_music_playing():
                        music.stop_music()
                    if keyboard_control:
                        send_command("dev0", "CYCLE")
                elif key == pygame.K_q:
                    send_command("dev0", "STOP")
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

            elif event.type == pygame.KEYUP and keyboard_control:
                key_name = pygame.key.name(event.key)
                if key_name in pressed_keys:
                    send_command("dev0", "STOP")
                    pressed_keys.discard(key_name)

            elif event.type == pygame.MOUSEBUTTONDOWN:
                pos = pygame.mouse.get_pos()
                for button in buttons:
                    if button.is_clicked(pos):
                        button.action()

    pygame.quit()
    GPIO.cleanup()
