import glob
import select
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
    "motorSpeedValue": config.DEFAULT_SPEED,

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

    elif line == "IR5":
        state.irMode = "LINE_FOLLOWER"
        print("〰 Line follower mode")

    elif line == "IR6":
        state.irMode = "WATCHDOG"
        print("🚨 Watchdog mode")


    # motor lock — instant, no password (physical possession of the
    # remote is the credential; see motor_lock.py for the password-gated
    # network path)
    elif line == "IRlock":
        state.irCommand = "LOCK"

    elif line == "IRunlock":
        state.irCommand = "UNLOCK"


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

    # Color buttons — speed control
    elif line == "IRyellow":
        state.irCommand = "SPEED_DOWN"

    elif line == "IRblue":
        state.irCommand = "SPEED_UP"

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
        # Suppress false positives while the robot is actively driving
        import mode_manager
        from state import DriveMode
        if mode_manager.current_mode() == DriveMode.IDLE:
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

# Guards candidate_ports()/identify() below — connect() runs independently
# on each dev's own reconnect thread, and without this two threads racing
# to reclaim ports at the same time can both open the *same* unclaimed
# /dev/ttyACM0|ttyUSB0 simultaneously (claimed_ports only excludes ports
# already stored in `arduinos`, which hasn't happened yet mid-identify).
# Confirmed on hardware: this produces pyserial's "device reports readiness
# to read but returned no data (device disconnected or multiple access on
# port?)" and makes the contended board fail WHOAMI over and over.
_connect_lock = threading.Lock()

# Boards identify themselves over serial rather than being pinned to a
# fixed port path — a replaced/reflashed board just needs to answer WHOAMI
# with one of these to be recognized, no matter which /dev/ttyACM*|ttyUSB*
# it enumerates as.
WHOAMI_REPLIES = {
    "I_AM_DEV00": "dev00",
    "I_AM_DEV01": "dev01",
}

IDENTIFY_TIMEOUT = 10  # seconds to wait for a WHOAMI reply after opening a port.
# dev00's VL53L0X init failure + servo/light startup sequence takes ~8s to
# clear before it reaches DEV00_READY and starts answering WHOAMI — the old
# 5s value abandoned the port about 1s before the board was ever ready.


def candidate_ports():
    return sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))


def identify(port):
    """Open `port`, ask WHOAMI, and return (dev_name, serial.Serial) for
    whichever board answers — or (None, None) if nothing claims it in time."""

    try:
        ser = serial.Serial(port, config.ARDUINO_BAUD, timeout=1)
    except Exception as e:
        print(f"❌ {port}: failed to open for identify: {e}")
        return None, None

    time.sleep(2)  # board resets on serial open — wait out its boot sequence

    ser.reset_input_buffer()
    ser.write(b"WHOAMI\n")

    # pyserial's own read timeout isn't reliably honored on this Pi/kernel —
    # a non-responding port can block ser.readline() forever, hanging the
    # whole app at startup. select() on the fd enforces the deadline at the
    # OS level regardless of what pyserial does internally.
    deadline = time.time() + IDENTIFY_TIMEOUT
    buf = b""

    try:

        while time.time() < deadline:

            remaining = deadline - time.time()
            ready, _, _ = select.select([ser.fileno()], [], [], min(1, remaining))

            if not ready:
                continue

            buf += ser.read(ser.in_waiting or 1)

            while b"\n" in buf:
                raw_line, buf = buf.split(b"\n", 1)
                dev = WHOAMI_REPLIES.get(raw_line.decode("utf-8", "ignore").strip())

                if dev:
                    return dev, ser

        print(f"⚠️ {port}: no WHOAMI reply, skipping")

    except (serial.SerialException, OSError) as e:
        print(f"❌ {port}: error during identify: {e}")

    ser.close()

    return None, None


def _resend_persisted_dev00_settings():
    """dev00's firmware has no persistent storage — every fresh connect
    (including a reconnect after a power-cycle) starts back at firmware
    defaults, so the speed/trim kida_db.py persisted need resending here."""
    try:
        import kida_db
        trim = kida_db.get_setting("wheel_trim")
        if trim is not None:
            set_wheel_trim(trim)
        speed = kida_db.get_setting("motor_speed")
        if speed is not None:
            set_motor_speed(speed)
    except Exception as e:
        print(f"⚠️ dev00 settings resend failed: {e}")


def connect(dev):
    """(Re)identify whichever connected port currently answers as `dev`."""

    with _connect_lock:

        claimed_ports = {s.port for s in arduinos.values() if s and s.is_open}

        for port in candidate_ports():

            if port in claimed_ports:
                continue

            found_dev, ser = identify(port)

            if found_dev == dev:
                arduinos[dev] = ser
                print(f"✅ Connected {dev} on {port}")
                if dev == "dev00":
                    _resend_persisted_dev00_settings()
                return ser

            if ser:
                ser.close()

    print(f"❌ {dev}: no board answered WHOAMI as {dev}")

    return None


# ─────────────────────────────────────────────
# Serial reader thread
# ─────────────────────────────────────────────

def read_loop(dev):

    while True:

        ser = arduinos.get(dev)

        if not ser or not ser.is_open:

            print(f"🔌 reconnecting {dev}")

            ser = connect(dev)

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

    for dev in WHOAMI_REPLIES.values():

        t = threads.get(dev)

        if t and t.is_alive():
            continue

        connect(dev)

        t = threading.Thread(
            target=read_loop,
            args=(dev,),
            daemon=True
        )

        t.start()

        threads[dev] = t

        print(f"🔄 thread started {dev}")


# ─────────────────────────────────────────────
# Send command
# ─────────────────────────────────────────────

def send_command(dev, cmd):

    # Motor lock — hard interlock enforced at the single choke point every
    # drive path (keyboard, IR, autonomous, line follower, watchdog, lane
    # detect, celebration, and the remote controller's /action calls) goes
    # through. STOP always gets through so the robot can still be halted.
    if dev == "dev00" and state.motor_lock and cmd != "STOP":
        print(f"🔒 Motor lock engaged — ignoring dev00 '{cmd}'")
        return

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
# Lights — driving vs. stopped
#
# These send LIGHT_BACK_ON/LIGHT_FRONT_OFF for "driving" and
# LIGHT_FRONT_ON/LIGHT_BACK_OFF for "stopped" — the literal opposite of
# what the names suggest. That's intentional: the physical LED strips are
# wired opposite to the Arduino firmware's FRONT_LIGHT/BACK_LIGHT pin
# naming (confirmed by watching the wrong strip light up on the actual
# hardware), so sending "LIGHT_FRONT_ON" lights the physical back strip.
# Centralised here so every call site (keyboard, IR, mode changes, the
# remote controller) gets the correct physical behaviour from one place.
# ─────────────────────────────────────────────

def set_driving_lights() -> None:
    send_command("dev01", "LIGHT_BACK_ON")
    send_command("dev01", "LIGHT_FRONT_OFF")


def set_stopped_lights() -> None:
    send_command("dev01", "LIGHT_FRONT_ON")
    send_command("dev01", "LIGHT_BACK_OFF")


# ─────────────────────────────────────────────
# Set motor speed (also remembers it for callers like vibration_guard
# that need to know the current cruising speed to restore afterward —
# dev00's firmware never reports SPEED back over serial, so this is the
# only source of truth for "what speed did we last command")
# ─────────────────────────────────────────────

def set_motor_speed(speed: int, dev: str = "dev00") -> None:
    speed = max(0, min(255, int(speed)))
    state.motorSpeedValue = speed
    send_command(dev, f"SPEED:{speed}")


# ─────────────────────────────────────────────
# Wheel trim — straight-line correction (see arduino00.ino's
# wheelTrimPercent). Firmware has no persistent storage, so the persisted
# value (kida_db.py) is resent every time dev00 (re)connects — see connect().
# ─────────────────────────────────────────────

def set_wheel_trim(trim: int, dev: str = "dev00") -> None:
    trim = max(-50, min(50, int(trim)))
    state.wheel_trim = trim
    send_command(dev, f"TRIM:{trim}")


# ─────────────────────────────────────────────
# Independent per-motor drive (tank-style QAWS scheme). Signed speed,
# positive = forward; goes through send_command so the motor lock
# interlock above still applies.
# ─────────────────────────────────────────────

def set_left_motor(speed: int, dev: str = "dev00") -> None:
    speed = max(-255, min(255, int(speed)))
    send_command(dev, f"LMOTOR:{speed}")


def set_right_motor(speed: int, dev: str = "dev00") -> None:
    speed = max(-255, min(255, int(speed)))
    send_command(dev, f"RMOTOR:{speed}")


# ─────────────────────────────────────────────
# Close all
# ─────────────────────────────────────────────

def close_all_arduinos():

    # Snapshot with list() — the daemon read_loop threads mutate this same
    # dict concurrently (pop on serial error, reassign on reconnect), which
    # raises "dictionary changed size during iteration" mid-shutdown and was
    # crashing emergency_stop_all() before it could finish (main.py would
    # then exit non-cleanly, restart, and reset motor_lock to True).
    for dev,ser in list(arduinos.items()):

        try:
            ser.close()
            print(f"🔒 closed {dev}")

        except Exception as e:

            print(f"⚠ close error {dev}: {e}")


# ─────────────────────────────────────────────
# Emergency stop — called on program exit (clean or crash) so a
# self-driving mode (AUTONOMOUS/obstacleAvoidance, line follower, watchdog)
# never keeps the Arduino moving after the Pi-side controller is gone.
# Bypasses the motor lock and mode machinery entirely since this must work
# even if state got corrupted or main.py died mid-startup.
# ─────────────────────────────────────────────

def emergency_stop_all():
    ser = arduinos.get("dev00")
    if ser and ser.is_open:
        for cmd in ("AUTO_OFF", "STOP"):
            try:
                ser.write((cmd + "\n").encode())
                print(f"🛑 dev00 ← {cmd}")
            except Exception as e:
                print(f"⚠ emergency stop failed dev00 '{cmd}': {e}")

    ser01 = arduinos.get("dev01")
    if ser01 and ser01.is_open:
        try:
            ser01.write(b"LIGHT_FRONT_ON\n")
            ser01.write(b"LIGHT_BACK_OFF\n")
        except Exception as e:
            print(f"⚠ emergency stop failed dev01: {e}")

    close_all_arduinos()