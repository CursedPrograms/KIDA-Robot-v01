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

# ── Track the last mode so we can send AUTO_OFF when leaving ──
_prev_mode: DriveMode | None = None


def _on_mode_changed(new_mode: DriveMode) -> None:
    """
    Internal hook called immediately after every mode change.
    Sends AUTO_ON / AUTO_OFF to the Arduino as needed.
    Also calls the project-level universal_mode_change hook.
    """
    global _prev_mode

    # ── Leaving autonomous ──
    if _prev_mode == DriveMode.AUTONOMOUS and new_mode != DriveMode.AUTONOMOUS:
        try:
            send_command("dev00", "AUTO_OFF")
            print("🤖 Autonomous OFF → Arduino stopped")
        except Exception as e:
            print(f"⚠️  AUTO_OFF: {e}")

    # ── Entering autonomous ──
    if new_mode == DriveMode.AUTONOMOUS and _prev_mode != DriveMode.AUTONOMOUS:
        try:
            send_command("dev00", "AUTO_ON")
            print("🤖 Autonomous ON → Arduino driving")
        except Exception as e:
            print(f"⚠️  AUTO_ON: {e}")

    _prev_mode = new_mode

    # Delegate to the project-wide hook
    try:
        universal_mode_change(new_mode)
    except Exception as e:
        print(f"⚠️  universal_mode_change: {e}")


def init_mode_control() -> None:
    """
    Register _on_mode_changed once at startup.
    Call this before entering the main loop.
    """
    register_on_mode_change(_on_mode_changed)


def switch_mode(number: int) -> None:
    """
    Switch to mode by number (1-4).
    The registered hook handles all side-effects.
    """
    mode_manager.set_mode_by_number(number)


def switch_mode_direct(mode: DriveMode) -> None:
    """Switch by DriveMode enum (e.g. for IDLE on quit)."""
    mode_manager.set_mode(mode)
