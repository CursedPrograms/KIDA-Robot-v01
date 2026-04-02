import serial
import time
import threading
import config
import state

# ─────────────────────────────────────────────
# Default state values
# ─────────────────────────────────────────────

_DEFAULTS = {

    "photoValue": "-",
    "uvValue": "-",
    "metalValue": "-",
    "ballSwitchValue": "-",
    "motionValue": "-",

    "lfLeftValue": "-",
    "lfMidValue": "-",
    "lfRightValue": "-",

    "laserValue": "-",
    "ultrasonic0Value": "-",
    "ultrasonic1Value": "-",

    "servoPosValue": "-",
    "buttonValue": "-",
    "motorSpeedValue": "-",

    "irCommand": "-",
    "irMode": "-",

    "systemStatus": "OK",
}

for k,v in _DEFAULTS.items():
    setattr(state,k,v)


# ─────────────────────────────────────────────
# Key mapping from Arduino → state
# ─────────────────────────────────────────────

KEY_MAP = {

    "MOTION": "motionValue",
    "PHOTO": "photoValue",
    "UV": "uvValue",
    "METAL": "metalValue",
    "BALL": "ballSwitchValue",

    "LFL": "lfLeftValue",
    "LFM": "lfMidValue",
    "LFR": "lfRightValue",

    "LASER": "laserValue",

    # ultrasonic sensors
    "ULTRASONIC0": "ultrasonic0Value",
    "ULTRASONIC1": "ultrasonic1Value",
    "US0": "ultrasonic0Value",
    "US1": "ultrasonic1Value",

    "SERVO": "servoPosValue",
    "BUTTON": "buttonValue",
    "SPEED": "motorSpeedValue",

    "STATUS": "systemStatus",
}


# ─────────────────────────────────────────────
# IR handler
# ─────────────────────────────────────────────

def handle_ir(line):

    # mode switching
    if line == "IR1":
        state.irMode = "IR_REMOTE"
        print("🎮 IR Remote mode")

    elif line == "IR2":
        state.irMode = "KEYBOARD"
        print("⌨️ Keyboard mode")

    elif line == "IR3":
        state.irMode = "AUTO"
        print("🤖 Autonomous mode")

    elif line == "IR4":
        state.irMode = "IDLE"
        print("🛑 Controller reset")


    # movement commands
    elif line == "IRforward":
        state.irCommand = "FORWARD"

    elif line == "IRdown":
        state.irCommand = "BACKWARD"

    elif line == "IRleft":
        state.irCommand = "LEFT"

    elif line == "IRright":
        state.irCommand = "RIGHT"


    # music buttons
    elif line == "IRplay":
        state.irCommand = "PLAY"

    elif line == "IRstop":
        state.irCommand = "STOP"

    elif line == "IRfastforward":
        state.irCommand = "SPEED_UP"

    elif line == "IRskipforward":
        state.irCommand = "NEXT_MODE"

    elif line == "IRrelease":
        state.irCommand = "STOP"

    # unknown IR command
    else:
        print(f"⚠️ Unknown IR: {line}")


# ─────────────────────────────────────────────
# Parse line like:
# MOTION:0 | PHOTO:512 | UV:33 | METAL:2
# ─────────────────────────────────────────────

def parse_sensor_line(line, dev_name):
    """
    Parse one line from Arduino that may include motion, photo, UV, metal, ball,
    and flattened LF sensors: L, M, R
    """

    parts = line.split("|")

    for p in parts:
        p = p.strip()
        if not p:
            continue

        # Split into key:value pairs (LF part may have multiple)
        for sub in p.split():
            if ":" not in sub:
                continue

            k, v = sub.split(":", 1)
            k = k.strip().upper()
            v = v.strip()

            if k == "L":
                state.lfLeftValue = v
            elif k == "M":
                state.lfMidValue = v
            elif k == "R":
                state.lfRightValue = v
            else:
                attr = KEY_MAP.get(k)
                if attr:
                    setattr(state, attr, v)
                else:
                    print(f"⚠️ {dev_name} unmapped {k}:{v}")


# ─────────────────────────────────────────────
# Dispatch incoming lines
# ─────────────────────────────────────────────

def dispatch(line, dev_name):
    line = line.strip()
    if not line:
        return

    # 1. Device ready messages
    if line in ("DEV0_READY", "DEV1_READY"):
        print(f"✅ {dev_name} ready")
        return

    # 2. IR commands
    if line.upper().startswith("IR"):
        handle_ir(line)
        return

    # 4. Key:value sensor lines
    if ":" in line:
        parse_sensor_line(line, dev_name)
        return

    # 5. Text alerts (legacy)
    uline = line.upper()
    if "MOTION DETECTED" in uline:
        state.systemStatus = "⚠ Motion"
        return
    if "METAL DETECTED" in uline:
        state.systemStatus = "⚡ Metal"
        return
    if "BALL SWITCH" in uline:
        state.systemStatus = "🏀 Ball"
        return

    # 6. Unknown line
    print(f"⚠️ {dev_name} unknown: {line}")


# ─────────────────────────────────────────────
# Serial connection manager
# ─────────────────────────────────────────────

arduinos = {}
threads = {}

PORTS = {
    "dev00": "/dev/ttyUSB0",
    "dev01": "/dev/ttyUSB1",
}


def connect(dev, port):

    try:

        ser = serial.Serial(port, config.ARDUINO_BAUD, timeout=1)

        time.sleep(2)

        arduinos[dev] = ser

        print(f"✅ Connected {dev} {port}")

        return ser

    except Exception as e:

        print(f"❌ {dev} connection failed: {e}")

        return None


# ─────────────────────────────────────────────
# Serial reader thread
# ─────────────────────────────────────────────

def read_loop(dev, port):

    while True:

        ser = arduinos.get(dev)

        if not ser or not ser.is_open:

            print(f"🔌 reconnecting {dev}")

            ser = connect(dev,port)

            if not ser:
                time.sleep(2)
                continue

        try:

            raw = ser.readline()

            if not raw:
                continue

            line = raw.decode("utf-8","ignore").strip()

            if line:
                dispatch(line,dev)

        except serial.SerialException:

            try:
                ser.close()
            except:
                pass

            arduinos.pop(dev,None)

            time.sleep(1)

        except Exception as e:

            print(f"⚠️ {dev} error: {e}")

            time.sleep(0.2)


# ─────────────────────────────────────────────
# Start threads
# ─────────────────────────────────────────────

def start_arduino_threads():

    for dev,port in PORTS.items():

        t = threads.get(dev)

        if t and t.is_alive():
            continue

        connect(dev,port)

        t = threading.Thread(
            target=read_loop,
            args=(dev,port),
            daemon=True
        )

        t.start()

        threads[dev] = t

        print(f"🔄 thread started {dev}")


# ─────────────────────────────────────────────
# Send command
# ─────────────────────────────────────────────

def send_command(dev, cmd):

    ser = arduinos.get(dev)

    if not ser or not ser.is_open:

        print(f"❌ {dev} not connected")

        return

    try:

        ser.write((cmd+"\n").encode())

        print(f"➡ {dev} ← {cmd}")

    except Exception as e:

        print(f"⚠ send failed {dev}: {e}")


# ─────────────────────────────────────────────
# Close all
# ─────────────────────────────────────────────

def close_all_arduinos():

    for dev,ser in arduinos.items():

        try:
            ser.close()
            print(f"🔒 closed {dev}")

        except Exception as e:

            print(f"⚠ close error {dev}: {e}")