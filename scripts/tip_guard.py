#!/usr/bin/env python3
"""
tip_guard.py — she stops when she tips over (WHIP's tilt safety, for KIDA-01).

Her MPU-6050 already knows how far she's tilted from her startup pose
(haptics._tilt_deg(); haptics.TIP_DEG is 30). Until now that only rumbled the
gamepad. This watches it in every mode:

    tilted past TIP_DEG for TIP_HOLD_S   -> motors stop (AUTO_OFF + STOP), state.tipped = True,
                                            anything driving her by itself (autonomous, line,
                                            lane, follow, MIND...) hands back to KEYBOARD,
                                            and she says so once
    while tipped                          -> arduino.send_command refuses every drive command
                                            (STOP always gets through, like the motor lock)
    back under TIP_DEG - CLEAR_MARGIN_DEG for CLEAR_HOLD_S  -> tipped clears; she doesn't
                                            start moving again by herself

/status shows `tipped` (her mind, RITA and RIFT read it).
"""

import threading
import time

import state

POLL_S           = 0.05
TIP_HOLD_S       = 0.25
CLEAR_MARGIN_DEG = 5
CLEAR_HOLD_S     = 1.0

# dev00 commands that move her (arduino.send_command checks them while she's tipped)
DRIVE_PREFIXES = ("FORWARD", "BACKWARD", "LEFT", "RIGHT", "AUTO_ON", "LMOTOR:", "RMOTOR:")

_thread = None
_stop = threading.Event()


def refuses(cmd: str) -> bool:
    """True if cmd would move her while she's tipped (a 0 speed is a stop, so it passes)."""
    if not getattr(state, "tipped", False):
        return False
    if cmd.startswith(("LMOTOR:", "RMOTOR:")):
        return cmd.split(":", 1)[1].strip() not in ("0", "-0")
    return cmd.startswith(DRIVE_PREFIXES)


def _tipped_now() -> None:
    import mode_manager
    from arduino import send_command, set_stopped_lights
    from state import DriveMode
    state.tipped = True
    send_command("dev00", "AUTO_OFF")
    send_command("dev00", "STOP")
    set_stopped_lights()
    if mode_manager.current_mode() not in (DriveMode.KEYBOARD, DriveMode.IR_REMOTE, DriveMode.IDLE):
        mode_manager.set_mode(DriveMode.KEYBOARD)
    state.systemStatus = "⚠ Tipping — motors stopped"
    print("🛑 Tip guard: she's tipping — motors stopped")
    try:
        import voice_engine
        voice_engine.speak_line("Whoa, I'm tipping! Stopping.", key="tip_guard")
    except Exception:
        pass


def _run() -> None:
    from haptics import TIP_DEG, _tilt_deg
    over_since = under_since = None
    while not _stop.is_set():
        time.sleep(POLL_S)
        tilt = _tilt_deg()
        now = time.monotonic()
        if tilt is None:
            over_since = under_since = None
            continue
        if not getattr(state, "tipped", False):
            if tilt > TIP_DEG:
                over_since = over_since or now
                if now - over_since >= TIP_HOLD_S:
                    _tipped_now()
                    under_since = None
            else:
                over_since = None
        else:
            if tilt < TIP_DEG - CLEAR_MARGIN_DEG:
                under_since = under_since or now
                if now - under_since >= CLEAR_HOLD_S:
                    state.tipped = False
                    over_since = None
                    state.systemStatus = "OK — back on her tracks"
                    print("✅ Tip guard: level again, drives allowed")
            else:
                under_since = None


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    state.tipped = False
    _stop.clear()
    _thread = threading.Thread(target=_run, daemon=True, name="TipGuard")
    _thread.start()
    print("🔧 Tip guard started")


def stop() -> None:
    _stop.set()
