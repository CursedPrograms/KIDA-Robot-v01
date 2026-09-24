# GPIO Pins
LED_PINS = [17, 27, 22, 18]

# Music
MUSIC_FOLDER = "/home/kida-01/Desktop/Kida-Robot/audio/music"
SUPPORTED_FORMATS = (".mp3", ".wav", ".ogg")

# Arduino
ARDUINO_PORT = "/dev/ttyUSB0"
ARDUINO_BAUD = 9600

# Camera
IMAGE_DIR = "captures/images"
VIDEO_DIR = "captures/videos"
CAM_ROTATION = 0

# Watchdog zone — normalized (0-1) (x1, y1, x2, y2) box within cam-0's frame
# that a detected person's center must fall inside to trigger the alarm.
# Default is the full frame (no change from plain "any person, anywhere").
# Narrow this to watch a specific area, e.g. a doorway on the right half:
#   WATCHDOG_ZONE = (0.5, 0.0, 1.0, 1.0)
WATCHDOG_ZONE = (0.0, 0.0, 1.0, 1.0)

# UI
SCREEN_SIZE = (1000, 500)
IMAGE_SIZE = (300, 300)
CHARACTER_FOLDER = "/home/kida-01/Desktop/Kida-Robot/images/characters"
BACKGROUND_IMAGE = "/home/kida-01/Desktop/Kida-Robot/images/background.jpeg"

# Motor
MAX_SPEED = 255
DEFAULT_SPEED = MAX_SPEED   # always start at full speed
SPEED_STEP = 50
MIN_SPEED = 100
# WASD diagonals (W+A, W+D, S+A, S+D): the inside track runs at this fraction
# of the outside one, so KIDA curves while still moving instead of spinning
# on the spot. 0 = pivot on the inside track, 1 = straight. See drive_mix.py.
CURVE_INNER_RATIO = 0.35

# Motor lock — password required to unlock (see motor_lock.py)
MOTOR_LOCK_PASSWORD = "1234"

# Bluetooth
BLUETOOTH_NAME = "KIDA01"
