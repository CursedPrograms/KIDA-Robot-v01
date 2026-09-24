# state.py

from enum import Enum

# ─────────────────────────────────────────────
#  Drive Mode Enum
# ─────────────────────────────────────────────
class DriveMode(Enum):
    KEYBOARD      = "KEYBOARD"
    IR_REMOTE     = "IR_REMOTE"
    AUTONOMOUS    = "AUTONOMOUS"
    LINE_FOLLOWER = "LINE_FOLLOWER"
    IDLE          = "IDLE"        # mode 4 / blackout state
    WATCHDOG      = "WATCHDOG"    # mode 6 / person-detection alarm
    LANE_DETECT   = "LANE_DETECT" # mode 7 / Hailo UFLD_v2 lane-following
    PERSON_FOLLOW = "PERSON_FOLLOW" # mode 8 / follow a person seen by cam-1's IMX500

# ─────────────────────────────────────────────
#  Active mode (single source of truth)
# ─────────────────────────────────────────────
drive_mode: DriveMode = DriveMode.KEYBOARD

# ─────────────────────────────────────────────
#  Voice Mode Enum
#  Both behaviors run inside kida_chat_wakeword.py's single Hailo Whisper
#  pipeline/thread (started once from main.py) rather than as two competing
#  scripts, since only one process can hold the mic and the wake-word
#  pipeline already needs the shared Hailo-8L multi-process group.
# ─────────────────────────────────────────────
class VoiceMode(Enum):
    WAKEWORD   = "WAKEWORD"    # gated: must say "Hey KIDA"/"Kira"/"Robot" first
    ALWAYS_ON  = "ALWAYS_ON"   # kida_chat.py behavior: transcribes continuously

voice_mode: VoiceMode = VoiceMode.WAKEWORD

# --- Basic Sensors ---
photoValue       = "PHOTO: N/A"
uvValue          = "UV: N/A"
metalValue       = "METAL: N/A"
ballSwitchValue  = "BALL: N/A"
motionValue      = "MOTION: N/A"

# --- Line Follower (3 sensors) ---
lfLeftValue      = "LF_LEFT: N/A"
lfMidValue       = "LF_MID: N/A"
lfRightValue     = "LF_RIGHT: N/A"

# --- Distance Sensors ---
laserValue       = "LASER: N/A" #For Obstacle Avoidance
lastSweepReading = ""   # "<angle>,<us1_cm>,<laser_mm>" — written by arduino.py, read by lidar_sweep.py
ultrasonic0Value  = "ULTRASONIC 0: N/A" #Uses the servo For Obstacle Avoidance
ultrasonic1Value  = "ULTRASONIC 1: N/A" #For Obstacle Avoidance

# --- Actuators & Controls ---
servoPosValue    = "SERVO: N/A" #For Obstacle Avoidance
buttonValue      = "BUTTON: N/A"
motorSpeedValue  = "SPEED: N/A" #For Obstacle Avoidance & User Control

# --- Debug/Status ---
systemStatus     = "SYSTEM: Booting..."

# --- YOLO inference results (written by camera_threads, read by watchdog + LLM) ---
detection_labels: list = []   # list of (class_name: str, confidence: float)
detection_boxes: list = []    # list of dicts: {"label": str, "conf": float, "box": (x1, y1, x2, y2)} — box is normalized 0-1 (cam-0 frame, post-mirror)

# --- IMX500 on-chip inference results (written by imx500_cam1.py) ---
cam1_detection_labels: list = []   # list of (class_name: str, confidence: float)
cam1_detection_boxes: list = []    # same dict shape as detection_boxes — normalized 0-1, cam-1 frame, post-mirror (as displayed)

# time.monotonic() of each camera's last detection pass — the two cameras
# aren't synced, and cam-0's boxes just stop updating when YOLO is toggled
# off, so person_follow_mode's stereo pairing checks both are fresh.
detection_boxes_ts: float = 0.0
cam1_detection_boxes_ts: float = 0.0

# --- Vibration guard (written by vibration_guard.py, read by haptics.py) ---
vibration_active: bool = False

# --- Gamepad (written by joystick_drive.py, read by hud_draw.py) ---
# Name of the pad plugged into *this* machine, or None — so the Pi HUD shows
# the Pi's pad and the controller HUD shows the PC's pad.
joystick_name: str | None = None
joystick_pending_mode: int | None = None   # LB/RB picked a mode, not applied yet

# --- Inner life (written by kida_mind_host.py, read by hud_draw.py) ---
mind_label: str | None = None   # e.g. "content", "lonely", "sleepy (asleep)"; None = no mind running

# --- Ambient face emotion (written by face_emotion_mode, read by HUD + LLM) ---
detected_emotion: tuple | None = None   # (label: str, confidence: float) of the largest face in view, or None

# --- UI runtime state (written by ui.py, read by server.py /status) ---
inference_on: bool = False

# --- Motor lock (written by motor_lock.py, enforced by arduino.send_command) ---
# Starts locked — the robot must be explicitly unlocked with the password
# every boot rather than driving away the moment it powers on.
motor_lock: bool = True

# --- Drive key scheme (KEYBOARD mode only) ---
# "WASD"  — W/S drive both motors together, A/D rotate in place (default)
# "QAWS"  — independent per-motor: Q/A = left motor fwd/back, W/S = right
#           motor fwd/back. Shared across all 3 UIs (local HUD, web,
#           remote controller) via this single flag.
drive_scheme: str = "WASD"

# --- Power monitor (written by ui.py INA219 poll, read by server.py /status) ---
bus_v:   float = 0.0
cur_ma:  float = 0.0
pwr_w:   float = 0.0
bat_pct: float = 0.0

# ─────────────────────────────────────────────
#  IR signals (written by arduino.py)
#  irCommand = None means "no command received yet"
#  This prevents handle_ir_controls() swallowing the very first command
#  because last_ir_command is also initialised to None.
# ─────────────────────────────────────────────
irCommand: str | None = None
irMode:    str        = "-"

# ─────────────────────────────────────────────
#  MPU6050 (written by mpu6050_module.py)
# ─────────────────────────────────────────────
mpu_ax = mpu_ay = mpu_az = 0
mpu_gx = mpu_gy = mpu_gz = 0
mpu_available: bool = False   # True only once the MPU6050 has actually initialized

# --- Wheel trim (written by arduino.set_wheel_trim, persisted via kida_db) ---
# -50..50, percent speed reduction applied to whichever motor over-drives a
# straight FORWARD/BACKWARD — see arduino00.ino's wheelTrimPercent.
wheel_trim: int = 0

