# mode_manager.py — KIDA drive-mode manager
#
#   1 → KEYBOARD     (WASD keys drive the robot)
#   2 → IR_REMOTE    (IR handset drives the robot)
#   3 → AUTONOMOUS   (state-machine / AI drives the robot)
#   4 → IDLE         (all motors stop, black input — always available)
#   5 → LINE_FOLLOWER
#   6 → WATCHDOG
#   7 → LANE_DETECT  (Hailo UFLD_v2 lane-following)
#
# Any input source (keyboard, IR, button) calls set_mode().
# All other modules read state.drive_mode.

import state
from state import DriveMode
from arduino import send_command, set_stopped_lights



# Then, anywhere in ui.py:
# Just call mode_manager.set_mode(...) or mode_manager.set_mode_by_number(...)
# The universal_mode_change() hook will automatically ru

# ── callbacks registered by other modules ──────────────────
_on_mode_change_hooks: list = []

def register_on_mode_change(fn):
    """Register a callback(new_mode: DriveMode) called on every mode change."""
    _on_mode_change_hooks.append(fn)

# Modes that manage their own motors (Arduino's own obstacleAvoidance loop
# for AUTONOMOUS, or a dedicated Python thread for the others). Sending STOP
# here would race against their own start-up command (e.g. AUTO_ON sent by
# mode_control right after this) and kill the first move — see mode_hooks.py.
_SELF_MANAGED_MODES = (DriveMode.AUTONOMOUS, DriveMode.LINE_FOLLOWER,
                       DriveMode.WATCHDOG, DriveMode.LANE_DETECT)


# ── public API ─────────────────────────────────────────────
def set_mode(new_mode: DriveMode, *, stop_motors: bool = True) -> None:
    """Switch to new_mode. Stops motors first for safety, except for
    self-managed modes (see _SELF_MANAGED_MODES) which handle their own
    motor start-up and would race against an unconditional STOP here."""
    if state.drive_mode == new_mode:
        return
    old = state.drive_mode
    state.drive_mode = new_mode
    print(f"🔀 Mode: {old.value} → {new_mode.value}")

    if new_mode == DriveMode.IDLE or (stop_motors and new_mode not in _SELF_MANAGED_MODES):
        _stop_all()

    for fn in _on_mode_change_hooks:
        try:
            fn(new_mode)
        except Exception as e:
            print(f"⚠️ mode hook error: {e}")

def set_mode_by_number(n: int) -> None:
    """
    Map 1-5 keypress or IR digit to a mode.
    4 is always IDLE (black input, motors stop) regardless of current mode.
    """
    mapping = {
        1: DriveMode.KEYBOARD,
        2: DriveMode.IR_REMOTE,
        3: DriveMode.AUTONOMOUS,
        4: DriveMode.IDLE,
        5: DriveMode.LINE_FOLLOWER,
        6: DriveMode.WATCHDOG,
        7: DriveMode.LANE_DETECT,
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

def is_line_follower() -> bool:
    return state.drive_mode == DriveMode.LINE_FOLLOWER

def is_watchdog() -> bool:
    return state.drive_mode == DriveMode.WATCHDOG

def is_lane_detect() -> bool:
    return state.drive_mode == DriveMode.LANE_DETECT



# ── internal ───────────────────────────────────────────────
def _stop_all() -> None:
    """Hard-stop motors and lights on both Arduinos."""
    try:
        send_command("dev00", "STOP")
        set_stopped_lights()
    except Exception as e:
        print(f"⚠️ stop_all error: {e}")
