# lidar_sweep.py — cheap software LIDAR: sweep the servo-mounted
# ultrasonic + laser through a range of angles and log each (angle,
# distance) point, the same mechanical idea as a single-beam LIDAR just
# lower resolution and slower.
#
# Each run is tagged with one sweep_id so kida_db.export_sweep_log_csv()
# can pull back just that scan later. Also grabs one cam-1 frame at sweep
# start and tags it onto every point in the scan — the offline mapper
# (mapper/build_3d_map.py) combines that frame's depth estimate with
# these angle/distance points to build a 3D map, run separately once
# kida-robot.service is stopped and the Hailo-8L is free.
#
# Stationary-scan only for now: pos_x_cm/pos_y_cm/heading_deg default to
# (0, 0, 0) — a fixed reference point, since there's no odometry yet to
# track where the robot has moved to between scans. A future "scan while
# driving" mode would pass in an accumulated pose instead.

import threading
import time
import uuid

import state
import mode_manager
from state import DriveMode
from arduino import send_command
import kida_db

SWEEP_START_DEG = 20
SWEEP_END_DEG   = 160
SWEEP_STEP_DEG  = 10
SETTLE_S        = 0.25   # matches the firmware's own 150ms settle + serial round-trip margin
CENTER_DEG      = 90

_running = threading.Event()


def _safe_to_sweep() -> bool:
    # Not a motor-drive action, but obstacleAvoidance()/scanLeft()/scanRight()
    # also drive this same servo — restrict to modes where nothing else is
    # actively using it, same reasoning as wheel_calibration.py.
    return mode_manager.current_mode() in (DriveMode.KEYBOARD, DriveMode.IDLE)


def _read_one_angle(angle: int, timeout_s: float = 1.0):
    """Send SERVO:<angle>, wait for the matching SWEEP: reply, return
    (us1_cm, laser_mm) or (None, None) if it never arrived in time."""
    state.lastSweepReading = ""
    send_command("dev00", f"SERVO:{angle}")

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        raw = state.lastSweepReading
        if raw:
            try:
                got_angle, us1, laser = raw.split(",")
                if int(got_angle) == angle:
                    return int(us1), int(laser)
            except (ValueError, IndexError):
                pass
        time.sleep(0.02)
    return None, None


def _capture_reference_frame(sweep_id: str) -> str | None:
    try:
        import camera_threads
        frame = camera_threads.get_last_cam1_frame()
        if frame is None:
            return None
        import cv2
        from pathlib import Path
        base = Path(__file__).resolve().parent.parent / "captures" / "sweeps"
        base.mkdir(parents=True, exist_ok=True)
        path = str(base / f"{sweep_id}.jpg")
        cv2.imwrite(path, cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
        return path
    except Exception as e:
        print(f"⚠️ lidar_sweep: reference frame capture failed: {e}")
        return None


def _run(sweep_id: str, pos_x_cm: float, pos_y_cm: float, heading_deg: float):
    state.systemStatus = f"Lidar sweep {sweep_id}: running"
    print(f"📡 Lidar sweep {sweep_id}: starting ({SWEEP_START_DEG}-{SWEEP_END_DEG} deg, step {SWEEP_STEP_DEG})")

    frame_path = _capture_reference_frame(sweep_id)
    points = 0

    for angle in range(SWEEP_START_DEG, SWEEP_END_DEG + 1, SWEEP_STEP_DEG):
        if not _running.is_set():
            break
        us1_cm, laser_mm = _read_one_angle(angle)
        kida_db.log_sweep_point(
            sweep_id, angle, us1_cm, laser_mm,
            pos_x_cm=pos_x_cm, pos_y_cm=pos_y_cm, heading_deg=heading_deg,
            frame_path=frame_path,
        )
        points += 1
        time.sleep(SETTLE_S)

    send_command("dev00", f"SERVO:{CENTER_DEG}")
    state.systemStatus = f"Lidar sweep {sweep_id}: done ({points} points)"
    print(f"📡 Lidar sweep {sweep_id}: done — {points} points logged")


def run_sweep(pos_x_cm: float = 0.0, pos_y_cm: float = 0.0, heading_deg: float = 0.0) -> str | None:
    """Kick off one sweep in a background thread. Returns the sweep_id to
    look up in kida_db later, or None if it's not currently safe to run
    (motor lock doesn't apply — this is scan-only — but the servo can't be
    shared with another mode that's actively using it)."""
    if not _safe_to_sweep():
        state.systemStatus = "Lidar sweep refused (not in KEYBOARD/IDLE)"
        print("⚠️ Lidar sweep refused — not in KEYBOARD/IDLE mode")
        return None
    if _running.is_set():
        return None

    sweep_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]

    def _wrapper():
        _running.set()
        try:
            _run(sweep_id, pos_x_cm, pos_y_cm, heading_deg)
        finally:
            _running.clear()

    threading.Thread(target=_wrapper, daemon=True, name="LidarSweep").start()
    return sweep_id
