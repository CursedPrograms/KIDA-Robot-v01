# ir_bridge.py — IR remote bridge, polled once per frame
#
# Reads state.irCommand / state.irMode (written by arduino.py) and
# dispatches to mode_control or motor commands.

import state
import config
import music
from state import DriveMode
from arduino import send_command
from mode_control import switch_mode
import mode_manager

_last_ir_command = None
_last_ir_mode    = None
motor_speed_ref  = [config.DEFAULT_SPEED]   # mutable box shared with caller

_IR_MODE_MAP = {
    "IR_REMOTE": DriveMode.IR_REMOTE,
    "KEYBOARD":  DriveMode.KEYBOARD,
    "AUTO":      DriveMode.AUTONOMOUS,
    "IDLE":      DriveMode.IDLE,
}


def poll(motor_speed_box: list) -> None:
    """
    Call once per frame from the main loop.
    motor_speed_box is a one-element list so the caller sees speed changes.
    """
    global _last_ir_command, _last_ir_mode

    # ── Mode change via IR ──
    ir_mode = getattr(state, "irMode", None)
    if ir_mode and ir_mode != _last_ir_mode:
        _last_ir_mode = ir_mode
        if ir_mode in _IR_MODE_MAP:
            mode_manager.set_mode(_IR_MODE_MAP[ir_mode])

    # ── Commands ──
    cmd = getattr(state, "irCommand", None)
    if cmd == _last_ir_command:
        return
    _last_ir_command = cmd
    if not cmd or cmd == "-":
        return

    print(f"🎮 IR cmd: {cmd}")

    # Mode select by number
    for num, aliases in {1: ("MODE1","1"), 2: ("MODE2","2"),
                         3: ("MODE3","3"), 4: ("MODE4","4")}.items():
        if cmd in aliases:
            switch_mode(num)
            return

    # Movement — IR_REMOTE mode only
    if not mode_manager.is_ir():
        return

    _MOVE_CMDS = {"FORWARD", "BACKWARD", "LEFT", "RIGHT"}
    if cmd in _MOVE_CMDS:
        send_command("dev00", cmd)
        send_command("dev01", "LIGHT_FRONT_ON")
        send_command("dev01", "LIGHT_BACK_OFF")
    elif cmd == "STOP":
        send_command("dev00", "STOP")
        send_command("dev01", "LIGHT_FRONT_OFF")
        send_command("dev01", "LIGHT_BACK_ON")
    elif cmd == "PLAY":
        music.play_next_track()
    elif cmd == "SPEED_UP":
        motor_speed_box[0] = min(motor_speed_box[0] + config.SPEED_STEP,
                                 config.MAX_SPEED)
        send_command("dev00", f"SPEED:{motor_speed_box[0]}")
    elif cmd == "NEXT_MODE":
        if mode_manager.is_ir():
            mode_manager.set_mode(DriveMode.KEYBOARD)
        else:
            mode_manager.set_mode(DriveMode.IR_REMOTE)
