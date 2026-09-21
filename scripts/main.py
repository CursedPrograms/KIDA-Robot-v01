import threading
import pygame
import signal
import sys
import os
import atexit
import urllib.request
import RPi.GPIO as GPIO

import kida_chat_wakeword as voice_ai

from server import run_flask_server
from leds import setup_leds, startup_led_fade
from arduino import start_arduino_threads, emergency_stop_all
from bluetooth import start_broadcast
from ui import run_ui
from ultralytics import YOLO
import ambient_narration
import vibration_guard
import face_emotion_mode
import kida_db
import mode_manager
import state

def signal_handler(sig, frame):
    print("👋 Exiting...")
    try:
        emergency_stop_all()
    except:
        pass
    try:
        pygame.mixer.music.stop()
        pygame.quit()
        GPIO.cleanup()
    except:
        pass
    sys.exit(0)


def download_model_if_missing(model_path):
    if not os.path.isfile(model_path):
        print(f"Model weights '{model_path}' not found. Downloading...")
        url = "https://github.com/ultralytics/assets/releases/download/v0.0.0/yolov8n.pt"
        try:
            urllib.request.urlretrieve(url, model_path)
            print(f"Downloaded YOLO model to {model_path}")
        except Exception as e:
            print(f"Failed to download model: {e}")
            raise


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    # Backstop for unhandled exceptions / any exit path that doesn't go
    # through os._exit() below — makes sure a self-driving mode never keeps
    # the Arduino moving after this process is gone.
    atexit.register(emergency_stop_all)

    # Persistence: settings survive a restart, mode changes and periodic
    # sensor snapshots get logged. Drive mode itself deliberately does NOT
    # get restored here — state.drive_mode stays hardcoded to KEYBOARD
    # (see state.py) so an unattended reboot never silently resumes an
    # autonomous/self-driving mode. Only non-driving preferences restore.
    kida_db.init_db()
    state.drive_scheme = kida_db.get_setting("drive_scheme", state.drive_scheme)
    voice_mode_name = kida_db.get_setting("voice_mode", state.voice_mode.name)
    try:
        state.voice_mode = state.VoiceMode[voice_mode_name]
    except KeyError:
        pass
    mode_manager.register_on_mode_change(kida_db.log_mode_change)
    kida_db.start_periodic_logging()

    setup_leds()
    startup_led_fade()
    start_arduino_threads()
    start_broadcast()
    ambient_narration.start()
    vibration_guard.start()
    face_emotion_mode.start()

    # music is now initialised inside run_ui via MusicPlayer()
    # init_music() call removed

    threading.Thread(target=run_flask_server, daemon=True).start()
    threading.Thread(target=voice_ai.main, daemon=True).start()

    script_dir   = os.path.dirname(os.path.abspath(__file__))
    model_path   = os.path.join(script_dir, "..", "resources", "models", "yolo11n.pt")
    tracker_path = os.path.join(script_dir, "trackers", "bytetrack.yaml")
    download_model_if_missing(model_path)

    model = YOLO(model_path)
    hard_quit = run_ui(model=model, mode="cam", task="detect", tracker_path=tracker_path)
    # os._exit() skips atexit, so the emergency stop has to be explicit here
    # too — otherwise a self-driving mode left running would never get told
    # to stop just because run_ui() returned.
    emergency_stop_all()
    # os._exit(), not sys.exit(): native threads owned by Hailo/PySerial/libcamera
    # aren't plain Python daemon threads, so they can keep the process alive
    # after run_ui() returns — leaving Flask/voice AI running as orphans on a
    # dead UI loop with pygame/GPIO already torn down (mixer errors, no drive
    # control). os._exit() forces real process termination so run.sh's
    # restart loop (which is what ESC's "soft quit" relies on) actually fires.
    os._exit(99 if hard_quit else 1)