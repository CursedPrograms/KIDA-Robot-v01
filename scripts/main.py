import threading
import pygame
import signal
import sys
import RPi.GPIO as GPIO

from flask_server import run_flask_server
from leds import setup_leds, startup_led_fade
from arduino import start_arduino_threads
from camera import picam2
from ui import run_ui
from ultralytics import YOLO
import os
import urllib.request

import kida_chat as voice_ai

# NOTE: music.py has been deleted.
# MusicPlayer is instantiated inside run_ui() and owns the full lifecycle.


def signal_handler(sig, frame):
    print("👋 Exiting...")
    try:
        if picam2:
            picam2.stop()
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
    setup_leds()
    startup_led_fade()
    start_arduino_threads()

    # music is now initialised inside run_ui via MusicPlayer()
    # init_music() call removed

    threading.Thread(target=run_flask_server, daemon=True).start()
    threading.Thread(target=voice_ai.main, daemon=True).start()

    script_dir   = os.path.dirname(os.path.abspath(__file__))
    model_path   = os.path.join(script_dir, "yolo11n.pt")
    tracker_path = os.path.join(script_dir, "trackers", "bytetrack.yaml")
    download_model_if_missing(model_path)

    model = YOLO(model_path)
    run_ui(model=model, mode="cam", task="detect", tracker_path=tracker_path)