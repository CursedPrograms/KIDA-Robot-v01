# mode_control.py — centralised mode-switching logic for KIDA
#
# The autonomous fix lives here: when entering AUTONOMOUS mode we
# immediately send AUTO_ON to the Arduino so it starts its
# obstacleAvoidance() loop.  When leaving we send AUTO_OFF.
#
# Usage:
#   from mode_control import switch_mode
#   switch_mode(3)   # → AUTONOMOUS

import mode_manager
from state import DriveMode
from arduino import send_command
from mode_hooks import universal_mode_change
from mode_manager import register_on_mode_change
import line_follow_mode
import watchdog_mode
import lane_detect_mode
import voice_engine

# ── Track the last mode so we can send AUTO_OFF when leaving ──
_prev_mode: DriveMode | None = None


def _on_mode_changed(new_mode: DriveMode) -> None:
    """
    Internal hook called immediately after every mode change.
    Sends AUTO_ON / AUTO_OFF to the Arduino as needed.
    Also calls the project-level universal_mode_change hook.
    """
    global _prev_mode

    was_lf  = (_prev_mode == DriveMode.LINE_FOLLOWER)
    is_lf   = (new_mode   == DriveMode.LINE_FOLLOWER)
    was_wd  = (_prev_mode == DriveMode.WATCHDOG)
    is_wd   = (new_mode   == DriveMode.WATCHDOG)
    was_ld  = (_prev_mode == DriveMode.LANE_DETECT)
    is_ld   = (new_mode   == DriveMode.LANE_DETECT)

    # ── Leaving autonomous ──
    if _prev_mode == DriveMode.AUTONOMOUS and new_mode != DriveMode.AUTONOMOUS:
        try:
            send_command("dev00", "AUTO_OFF")
            print("🤖 Autonomous OFF → Arduino stopped")
        except Exception as e:
            print(f"⚠️  AUTO_OFF: {e}")

    # ── Leaving line follower ──
    if was_lf and not is_lf:
        try:
            line_follow_mode.stop()
            print("〰 Line follower OFF")
        except Exception as e:
            print(f"⚠️  LINE_FOLLOWER stop: {e}")

    # ── Leaving watchdog ──
    if was_wd and not is_wd:
        try:
            watchdog_mode.stop()
            print("🚨 Watchdog OFF")
        except Exception as e:
            print(f"⚠️  WATCHDOG stop: {e}")

    # ── Leaving lane detect ──
    if was_ld and not is_ld:
        try:
            lane_detect_mode.stop()
            print("🛣️  Lane detect OFF")
        except Exception as e:
            print(f"⚠️  LANE_DETECT stop: {e}")

    # ── Entering autonomous ──
    if new_mode == DriveMode.AUTONOMOUS and _prev_mode != DriveMode.AUTONOMOUS:
        try:
            send_command("dev00", "AUTO_ON")
            print("🤖 Autonomous ON → Arduino driving")
        except Exception as e:
            print(f"⚠️  AUTO_ON: {e}")

    _prev_mode = new_mode

    # Delegate to the project-wide hook (may send STOP for non-autonomous modes)
    try:
        universal_mode_change(new_mode)
    except Exception as e:
        print(f"⚠️  universal_mode_change: {e}")

    # ── Entering line follower (start AFTER hook so STOP arrives first) ──
    if is_lf and not was_lf:
        try:
            line_follow_mode.start()
            print("〰 Line follower ON")
        except Exception as e:
            print(f"⚠️  LINE_FOLLOWER start: {e}")

    # ── Entering watchdog ──
    if is_wd and not was_wd:
        try:
            watchdog_mode.start()
            print("🚨 Watchdog ON")
        except Exception as e:
            print(f"⚠️  WATCHDOG start: {e}")

    # ── Entering lane detect ──
    if is_ld and not was_ld:
        try:
            lane_detect_mode.start()
            print("🛣️  Lane detect ON")
        except Exception as e:
            print(f"⚠️  LANE_DETECT start: {e}")

    # ── Voice acknowledgment ──
    try:
        voice_engine.announce_mode(new_mode)
    except Exception as e:
        print(f"⚠️  voice announce: {e}")


def init_mode_control() -> None:
    """
    Register _on_mode_changed once at startup.
    Call this before entering the main loop.
    """
    register_on_mode_change(_on_mode_changed)


def switch_mode(number: int) -> None:
    """
    Switch to mode by number (1-7).
    The registered hook handles all side-effects.
    """
    mode_manager.set_mode_by_number(number)


def switch_mode_direct(mode: DriveMode) -> None:
    """Switch by DriveMode enum (e.g. for IDLE on quit)."""
    mode_manager.set_mode(mode)
