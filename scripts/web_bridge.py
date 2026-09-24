# web_bridge.py — shared interface between Flask routes and the robot runtime
#
# Flask routes run in a worker thread; the robot runtime (music player, mode
# manager) runs in the main thread.  This module holds the live references so
# server.py can call into them safely.

import os
import time

_music_ctrl           = None
_inference_toggle_fn  = None

# Fixed path, overwritten per upload — mirrors kida_chat_wakeword.AUDIO_PATH's
# "reuse one file" pattern rather than accumulating one file per recording.
_VOICE_UPLOAD_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'audio', 'snippets', 'web_voice_upload.webm'
)


def transcribe_upload(file_storage) -> str:
    """Save a browser-recorded clip and run it through the same Whisper→
    voice_commands→LLM pipeline the wake-word loop uses. See
    kida_chat_wakeword.transcribe_file() for the concurrency-safe handoff."""
    file_storage.save(_VOICE_UPLOAD_PATH)
    import kida_chat_wakeword
    return kida_chat_wakeword.transcribe_file(_VOICE_UPLOAD_PATH)

_DRIVE_DIRECTIONS = {
    'move_forward':  'FORWARD',
    'move_backward': 'BACKWARD',
    'move_left':     'LEFT',
    'move_right':    'RIGHT',
}

# ── Dead-man's switch for web-driven movement ───────────────────────────
# The website resends a "still driving" heartbeat every 300ms while a drive
# key is held. If the browser tab crashes or the network drops mid-drive,
# the stop request can never arrive — so auto-stop if a heartbeat is late.
_WEB_DRIVE_TIMEOUT_S = 0.8
_last_web_drive_ts    = 0.0
_web_driving          = False


def check_web_drive_timeout() -> None:
    """Call once per main-loop frame (mirrors check_recording_timeout())."""
    global _web_driving
    if _web_driving and (time.time() - _last_web_drive_ts) > _WEB_DRIVE_TIMEOUT_S:
        from arduino import send_command, set_stopped_lights
        send_command("dev00", "STOP")
        set_stopped_lights()
        _web_driving = False
        print("⏱️  Web drive heartbeat lost — auto-stopped")


def is_driving() -> bool:
    """True while the web/remote/gamepad drive is holding the motors on."""
    return _web_driving


def register_music(mc) -> None:
    global _music_ctrl
    _music_ctrl = mc


def register_inference_toggle(fn) -> None:
    """fn: ui.py's toggle_inference() closure, so /action can flip cam-0
    YOLO the same way the local 'I' key does."""
    global _inference_toggle_fn
    _inference_toggle_fn = fn


def music_playing() -> bool:
    return bool(_music_ctrl and _music_ctrl.is_playing())


def _unit(value) -> float:
    """Coerce a joystick value from the request JSON into [-1, 1]."""
    try:
        return max(-1.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def action(command: str, password: str | None = None,
           left=None, right=None, angle=None) -> bool:
    """Dispatch a web action command. Returns True if recognised and it
    succeeded (motor_lock_off returns False on a wrong password).
    left/right are only used by 'joy_drive' (per-side throttle, -1..1),
    angle only by 'servo_aim' (degrees, 90 = straight ahead)."""
    from mode_control import switch_mode

    if command == 'music_play':
        if _music_ctrl:
            if _music_ctrl.is_playing():
                _music_ctrl.skip()
            else:
                _music_ctrl.start()
    elif command == 'music_skip':
        if _music_ctrl:
            _music_ctrl.skip()
    elif command == 'music_stop':
        if _music_ctrl:
            _music_ctrl.stop()
    elif command == 'mode_1':
        switch_mode(1)
    elif command == 'mode_2':
        switch_mode(2)
    elif command == 'mode_3':
        switch_mode(3)
    elif command == 'mode_4':
        switch_mode(4)
    elif command == 'mode_5':
        switch_mode(5)
    elif command == 'mode_6':
        switch_mode(6)
    elif command == 'mode_7':
        switch_mode(7)
    elif command == 'mode_8':
        switch_mode(8)
    elif command == 'voice_mode_wakeword':
        import state
        state.voice_mode = state.VoiceMode.WAKEWORD
    elif command == 'voice_mode_always_on':
        import state
        state.voice_mode = state.VoiceMode.ALWAYS_ON
    elif command == 'photo':
        import camera_actions, sfx
        camera_actions.take_photo()
        sfx.play("camera_shutter.mp3")
    elif command == 'video_start':
        import camera_actions, sfx
        camera_actions.start_video()
        sfx.play("video_reel.mp3")
    elif command == 'video_stop':
        import camera_actions
        camera_actions.stop_video()
    elif command == 'video_toggle':
        # Gamepad right trigger — a single button, so it needs the robot's
        # own idea of whether it's recording (the PC/browser can't know).
        import camera_actions, sfx
        if camera_actions.recording:
            camera_actions.stop_video()
        else:
            camera_actions.start_video()
            sfx.play("video_reel.mp3")
    elif command == 'servo_aim':
        # Gamepad right stick — point the servo-mounted US1/laser (and
        # anything else on that mount) left/right. Same mode restriction as
        # lidar_sweep: AUTONOMOUS's obstacleAvoidance() scans with this servo
        # too, and a sweep in progress owns it.
        import mode_manager, lidar_sweep
        from state import DriveMode
        from arduino import send_command
        if (mode_manager.current_mode() not in (DriveMode.KEYBOARD, DriveMode.IDLE)
                or lidar_sweep._running.is_set()):
            return False
        try:
            deg = max(0, min(180, int(float(angle))))
        except (TypeError, ValueError):
            return False
        send_command("dev00", f"SERVO:{deg}")
        import camera_actions
        camera_actions.cycle_camera()
    elif command == 'save_inference':
        import camera_actions
        camera_actions.save_inference_photo()
    elif command in _DRIVE_DIRECTIONS:
        import mode_manager
        from arduino import send_command, set_driving_lights
        if mode_manager.is_keyboard():
            global _last_web_drive_ts, _web_driving
            send_command("dev00", _DRIVE_DIRECTIONS[command])
            set_driving_lights()
            _last_web_drive_ts = time.time()
            _web_driving = True
    elif command in ('move_stop', 'hard_stop'):
        from arduino import send_command, set_stopped_lights
        send_command("dev00", "STOP")
        set_stopped_lights()
        _web_driving = False
        if command == 'hard_stop' and _music_ctrl:
            _music_ctrl.stop()
    elif command in ('left_forward', 'left_backward', 'right_forward', 'right_backward'):
        # QAWS tank scheme — independent per-motor, web equivalent of
        # scripts/event_handler.py's Q/A/W/S handling.
        import mode_manager, state
        from arduino import set_left_motor, set_right_motor, set_driving_lights
        if mode_manager.is_keyboard():
            speed = state.motorSpeedValue if isinstance(state.motorSpeedValue, int) else 0
            if command == 'left_forward':    set_left_motor(speed)
            elif command == 'left_backward': set_left_motor(-speed)
            elif command == 'right_forward': set_right_motor(speed)
            elif command == 'right_backward': set_right_motor(-speed)
            set_driving_lights()
            _last_web_drive_ts = time.time()
            _web_driving = True
    elif command == 'joy_drive':
        # Analog joystick drive from the website (Gamepad API) or the remote
        # controller (pygame) — the stick is plugged into the browser/PC,
        # never the robot. Both clients do the arcade mix themselves and send
        # per-side throttle in [-1, 1], scaled here by the current speed
        # setting so Speed +/- and X still cap how fast the stick can go.
        # Clients resend while the stick is deflected, so the same dead-man
        # timeout as the drive keys covers a dropped connection.
        import mode_manager, state
        from arduino import (set_left_motor, set_right_motor,
                             set_driving_lights, set_stopped_lights)
        if mode_manager.is_keyboard():
            speed = state.motorSpeedValue if isinstance(state.motorSpeedValue, int) else 0
            l, r = _unit(left), _unit(right)
            set_left_motor(round(l * speed))
            set_right_motor(round(r * speed))
            moving = bool(l or r)
            if moving and not _web_driving:
                set_driving_lights()
            elif not moving and _web_driving:
                set_stopped_lights()
            _last_web_drive_ts = time.time()
            _web_driving = moving
    elif command == 'left_stop':
        from arduino import set_left_motor
        set_left_motor(0)
    elif command == 'right_stop':
        from arduino import set_right_motor
        set_right_motor(0)
    elif command == 'scheme_wasd':
        import state
        state.drive_scheme = "WASD"
    elif command == 'scheme_qaws':
        import state
        state.drive_scheme = "QAWS"
    elif command == 'speed_cycle':
        import config, state
        from arduino import set_motor_speed
        current = state.motorSpeedValue if isinstance(state.motorSpeedValue, int) else config.DEFAULT_SPEED
        new_speed = current + config.SPEED_STEP
        if new_speed > config.MAX_SPEED:
            new_speed = config.MIN_SPEED
        set_motor_speed(new_speed)
    elif command == 'speed_up':
        import config, state
        from arduino import set_motor_speed
        current = state.motorSpeedValue if isinstance(state.motorSpeedValue, int) else config.DEFAULT_SPEED
        set_motor_speed(min(current + config.SPEED_STEP, config.MAX_SPEED))
    elif command == 'speed_down':
        import config, state
        from arduino import set_motor_speed
        current = state.motorSpeedValue if isinstance(state.motorSpeedValue, int) else config.DEFAULT_SPEED
        set_motor_speed(max(current - config.SPEED_STEP, config.MIN_SPEED))
    elif command == 'trim_up':
        import wheel_calibration
        wheel_calibration.nudge_trim(1)
    elif command == 'trim_down':
        import wheel_calibration
        wheel_calibration.nudge_trim(-1)
    elif command == 'calibrate_wheels':
        import wheel_calibration
        return wheel_calibration.run_calibration()
    elif command == 'lidar_sweep':
        import lidar_sweep
        return lidar_sweep.run_sweep()
    elif command == 'leds_toggle':
        import leds
        leds.toggle_leds()
    elif command == 'leds_effects_toggle':
        import leds
        leds.toggle_effects()
    elif command == 'inference_toggle':
        if _inference_toggle_fn:
            _inference_toggle_fn()
    elif command == 'motor_lock_on':
        import motor_lock
        motor_lock.lock()
    elif command == 'motor_lock_off':
        import motor_lock
        return motor_lock.try_unlock(password or "")
    else:
        return False
    return True
