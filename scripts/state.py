# state.py

from enum import Enum

# ─────────────────────────────────────────────
#  Drive Mode Enum
# ─────────────────────────────────────────────
class DriveMode(Enum):
    KEYBOARD   = "KEYBOARD"
    IR_REMOTE  = "IR_REMOTE"
    AUTONOMOUS = "AUTONOMOUS"
    IDLE       = "IDLE"          # mode 4 / blackout state

# ─────────────────────────────────────────────
#  Active mode (single source of truth)
# ─────────────────────────────────────────────
drive_mode: DriveMode = DriveMode.KEYBOARD

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
ultrasonic0Value  = "ULTRASONIC 0: N/A" #Uses the servo For Obstacle Avoidance
ultrasonic1Value  = "ULTRASONIC 1: N/A" #For Obstacle Avoidance

# --- Actuators & Controls ---
servoPosValue    = "SERVO: N/A" #For Obstacle Avoidance
buttonValue      = "BUTTON: N/A"
motorSpeedValue  = "SPEED: N/A" #For Obstacle Avoidance & User Control

# --- Debug/Status ---
systemStatus     = "SYSTEM: Booting..."

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

