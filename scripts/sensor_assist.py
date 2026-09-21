# sensor_assist.py — passive sensor safety layer
#
# Runs as a daemon thread from startup.
#
# Motor-affecting behaviours (ball-switch bump-stop, proximity emergency
# stop) only act in KEYBOARD/IR_REMOTE, where this thread is the sole
# source of motor commands. AUTONOMOUS drives via the Arduino's own onboard
# obstacleAvoidance() loop (see mode_manager._SELF_MANAGED_MODES) — sending
# STOP from here would race it. LINE_FOLLOWER's own 50ms loop is likewise
# the sole owner of dev00's motors while active, so it does its own inline
# ball/proximity check (line_follow_mode.py) instead — an external STOP
# from this thread would just get overwritten by that loop's very next
# FORWARD/LEFT/RIGHT tick.
#
# Non-motor behaviours (lights, status warnings) don't fight anything, so
# they also run during LINE_FOLLOWER.
#
# Behaviours:
#   Ball switch   → collision bump-stop (motors + lights)      [KEYBOARD/IR_REMOTE only]
#   Proximity     → warning / emergency stop (ultrasonic/laser) [KEYBOARD/IR_REMOTE only]
#   Photo sensor  → auto front-lights when dark, off when bright
#   Metal sensor  → status warning with cooldown
#   UV sensor     → status warning with cooldown

import threading
import time
import logging

import state
import mode_manager
from state import DriveMode
from arduino import send_command, set_stopped_lights

logger = logging.getLogger(__name__)

POLL_INTERVAL     = 0.1     # seconds
STOP_DIST_CM      = 8       # emergency stop threshold
WARN_DIST_CM      = 20      # proximity warning threshold
DARK_THRESHOLD    = 120     # photo sensor value below this → lights on
UV_WARN_THRESHOLD = 60      # UV value above this → warn
METAL_COOLDOWN    = 5.0     # seconds between metal warnings
UV_COOLDOWN       = 10.0    # seconds between UV warnings

_stop_event = threading.Event()
_thread: threading.Thread | None = None
_lights_auto = False          # True when we turned front lights on automatically


def _parse_int(raw, default=None):
    """Parse a sensor value that may arrive as 'KEY: 512' or '512'."""
    if raw is None:
        return default
    try:
        return int(float(str(raw).split(":")[-1].strip()))
    except (ValueError, AttributeError):
        return default


def _lights_and_status_active() -> bool:
    """Modes where the non-motor behaviours (lights, metal/UV warnings)
    are useful — anywhere the robot is actively moving under a mode that
    doesn't already handle its own ambient sensors."""
    return mode_manager.current_mode() in (
        DriveMode.KEYBOARD, DriveMode.IR_REMOTE, DriveMode.LINE_FOLLOWER,
    )


def _motor_override_active() -> bool:
    """Modes where this thread is the sole source of motor commands, so
    it's safe for it to send STOP directly. See module docstring."""
    return mode_manager.current_mode() in (DriveMode.KEYBOARD, DriveMode.IR_REMOTE)


def _run():
    global _lights_auto
    logger.info("Sensor assist started")
    last_ball       = False
    last_metal_warn = 0.0
    last_uv_warn    = 0.0
    prox_stopped    = False

    while not _stop_event.is_set():
        time.sleep(POLL_INTERVAL)

        if not _lights_and_status_active():
            continue

        now = time.time()

        # ── Ball switch: collision bump-stop ────────────────────────────────
        if _motor_override_active():
            ball = _parse_int(state.ballSwitchValue)
            hit  = ball == 1
            if hit and not last_ball:
                send_command("dev00", "STOP")
                set_stopped_lights()
                state.systemStatus = "⚠ Collision — bump stop"
                print("🏀 Sensor assist: collision bump-stop")
            last_ball = hit

        # ── Proximity: emergency stop / warning ─────────────────────────────
        dists = [
            v for v in (
                _parse_int(state.laserValue),
                _parse_int(state.ultrasonic0Value),
                _parse_int(state.ultrasonic1Value),
            )
            if v is not None and v > 0
        ]
        if dists:
            closest = min(dists)
            if closest < STOP_DIST_CM:
                if _motor_override_active() and not prox_stopped:
                    send_command("dev00", "STOP")
                    state.systemStatus = f"⚠ Too close ({closest} cm)"
                    print(f"🛑 Sensor assist: emergency stop — {closest} cm")
                    prox_stopped = True
            elif closest < WARN_DIST_CM:
                state.systemStatus = f"⚠ Obstacle {closest} cm"
                prox_stopped = False
            else:
                prox_stopped = False

        # ── Photo sensor: auto front-lights ─────────────────────────────────
        # LIGHT_BACK_ON/OFF is what actually lights the physical front strip
        # here — see the comment on arduino.set_driving_lights().
        photo = _parse_int(state.photoValue)
        if photo is not None:
            if photo < DARK_THRESHOLD and not _lights_auto:
                send_command("dev01", "LIGHT_BACK_ON")
                _lights_auto = True
                print("💡 Sensor assist: dark — auto lights ON")
            elif photo >= DARK_THRESHOLD and _lights_auto:
                send_command("dev01", "LIGHT_BACK_OFF")
                _lights_auto = False
                print("💡 Sensor assist: bright — auto lights OFF")

        # ── Metal detection: cooldown status warn ───────────────────────────
        metal = _parse_int(state.metalValue)
        if metal == 1 and now - last_metal_warn > METAL_COOLDOWN:
            state.systemStatus = "⚡ Metal detected"
            print("⚡ Sensor assist: metal detected")
            last_metal_warn = now

        # ── UV: cooldown status warn ────────────────────────────────────────
        uv = _parse_int(state.uvValue)
        if uv is not None and uv > UV_WARN_THRESHOLD and now - last_uv_warn > UV_COOLDOWN:
            state.systemStatus = f"☀ High UV ({uv})"
            print(f"☀ Sensor assist: high UV ({uv})")
            last_uv_warn = now

    if _lights_auto:
        send_command("dev01", "LIGHT_BACK_OFF")
        _lights_auto = False
    logger.info("Sensor assist stopped")


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_run, daemon=True, name="SensorAssist")
    _thread.start()
    print("🔧 Sensor assist started")


def stop() -> None:
    _stop_event.set()
    if _thread:
        _thread.join(timeout=1.0)
