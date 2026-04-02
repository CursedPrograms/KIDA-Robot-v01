# mode_manager.py — KIDA drive-mode manager
#
# Three active modes + one idle/blackout:
#   1 → KEYBOARD    (WASD keys drive the robot)
#   2 → IR_REMOTE   (IR handset drives the robot)
#   3 → AUTONOMOUS  (state-machine / AI drives the robot)
#   4 → IDLE        (all motors stop, black input — always available)
#
# Any input source (keyboard, IR, button) calls set_mode().
# All other modules read state.drive_mode.

import state
from state import DriveMode
from arduino import send_command



# Then, anywhere in ui.py:
# Just call mode_manager.set_mode(...) or mode_manager.set_mode_by_number(...)
# The universal_mode_change() hook will automatically ru

# ── callbacks registered by other modules ──────────────────
_on_mode_change_hooks: list = []

def register_on_mode_change(fn):
    """Register a callback(new_mode: DriveMode) called on every mode change."""
    _on_mode_change_hooks.append(fn)

# ── public API ─────────────────────────────────────────────
def set_mode(new_mode: DriveMode, *, stop_motors: bool = True) -> None:
    """Switch to new_mode. Always stops motors first for safety."""
    if state.drive_mode == new_mode:
        return
    old = state.drive_mode
    state.drive_mode = new_mode
    print(f"🔀 Mode: {old.value} → {new_mode.value}")

    if stop_motors or new_mode == DriveMode.IDLE:
        _stop_all()

    for fn in _on_mode_change_hooks:
        try:
            fn(new_mode)
        except Exception as e:
            print(f"⚠️ mode hook error: {e}")

def set_mode_by_number(n: int) -> None:
    """
    Map 1-4 keypress or IR digit to a mode.
    4 is always IDLE (black input, motors stop) regardless of current mode.
    """
    mapping = {
        1: DriveMode.KEYBOARD,
        2: DriveMode.IR_REMOTE,
        3: DriveMode.AUTONOMOUS,
        4: DriveMode.IDLE,
    }
    if n not in mapping:
        print(f"⚠️ Invalid mode number: {n}")
        return
    set_mode(mapping[n])

def current_mode() -> DriveMode:
    return state.drive_mode

def is_keyboard() -> bool:
    return state.drive_mode == DriveMode.KEYBOARD

def is_ir() -> bool:
    return state.drive_mode == DriveMode.IR_REMOTE

def is_autonomous() -> bool:
    return state.drive_mode == DriveMode.AUTONOMOUS

def is_idle() -> bool:
    return state.drive_mode == DriveMode.IDLE



# ── internal ───────────────────────────────────────────────
def _stop_all() -> None:
    """Hard-stop motors and lights on both Arduinos."""
    try:
        send_command("dev00", "STOP")
        send_command("dev01", "LIGHT_FRONT_OFF")
        send_command("dev01", "LIGHT_BACK_ON")
    except Exception as e:
        print(f"⚠️ stop_all error: {e}")
