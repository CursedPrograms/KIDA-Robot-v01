# kida_db.py — SQLite persistence: settings, drive-mode history, sensor stats
#
# One file (data/kida.db), short-lived connections per call rather than a
# single shared connection — the write volume here is low (a settings
# change, a mode switch, a periodic sensor snapshot every SNAPSHOT_INTERVAL_S
# seconds), so there's no need for a long-lived connection juggled across
# threads. SQLite's own file locking already serializes concurrent writers;
# _lock plus a connect `timeout` just avoids a transient "database is
# locked" surfacing as a visible error under momentary contention on an
# SD card.

import json
import sqlite3
import threading
import time
from pathlib import Path

import state

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = str(BASE_DIR / "data" / "kida.db")

SNAPSHOT_INTERVAL_S = 30  # sensor_log + settings-sync cadence

_lock = threading.Lock()
_stop_event = threading.Event()
_thread: threading.Thread | None = None


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")  # readers don't block the writer
    return conn


def init_db() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with _lock, _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mode_history (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                ts   TEXT NOT NULL,
                mode TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sweep_log (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                ts       TEXT NOT NULL,
                sweep_id TEXT NOT NULL,
                angle_deg     INTEGER NOT NULL,
                us1_cm        INTEGER,
                laser_mm      INTEGER,
                pos_x_cm      REAL,
                pos_y_cm      REAL,
                heading_deg   REAL,
                frame_path    TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sensor_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ts         TEXT NOT NULL,
                drive_mode TEXT,
                laser      INTEGER,
                us0        INTEGER,
                us1        INTEGER,
                photo      INTEGER,
                uv         INTEGER,
                metal      INTEGER,
                ball       INTEGER,
                lf_left    INTEGER,
                lf_mid     INTEGER,
                lf_right   INTEGER,
                motion     INTEGER,
                bus_v      REAL,
                cur_ma     REAL,
                bat_pct    REAL
            )
        """)


# ── settings (key/value, JSON-encoded so any JSON-safe type round-trips) ──

def get_setting(key: str, default=None):
    with _lock, _connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row[0])
    except (ValueError, TypeError):
        return default


def set_setting(key: str, value) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )


# ── mode history — register with mode_manager.register_on_mode_change ──

def log_mode_change(new_mode) -> None:
    name = getattr(new_mode, "value", str(new_mode))
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO mode_history (ts, mode) VALUES (?, ?)",
            (time.strftime("%Y-%m-%d %H:%M:%S"), name),
        )


# ── lidar-style sweep points — see lidar_sweep.py ──

def log_sweep_point(sweep_id: str, angle_deg: int, us1_cm, laser_mm,
                     pos_x_cm: float = 0.0, pos_y_cm: float = 0.0,
                     heading_deg: float = 0.0, frame_path: str | None = None) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            """INSERT INTO sweep_log
               (ts, sweep_id, angle_deg, us1_cm, laser_mm,
                pos_x_cm, pos_y_cm, heading_deg, frame_path)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (time.strftime("%Y-%m-%d %H:%M:%S"), sweep_id, angle_deg, us1_cm, laser_mm,
             pos_x_cm, pos_y_cm, heading_deg, frame_path),
        )


def export_sweep_log_csv(out_path: str, sweep_id: str | None = None) -> int:
    """Dump sweep_log (optionally filtered to one sweep_id) to a flat CSV —
    the hand-off point for cobol/ (no sqlite driver there) and for the
    offline mapper's point-cloud math. Returns the row count written."""
    with _lock, _connect() as conn:
        if sweep_id:
            rows = conn.execute(
                "SELECT ts, sweep_id, angle_deg, us1_cm, laser_mm, pos_x_cm, pos_y_cm, "
                "heading_deg, frame_path FROM sweep_log WHERE sweep_id = ? ORDER BY id",
                (sweep_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT ts, sweep_id, angle_deg, us1_cm, laser_mm, pos_x_cm, pos_y_cm, "
                "heading_deg, frame_path FROM sweep_log ORDER BY id"
            ).fetchall()

    with open(out_path, "w") as f:
        f.write("ts,sweep_id,angle_deg,us1_cm,laser_mm,pos_x_cm,pos_y_cm,heading_deg,frame_path\n")
        for row in rows:
            f.write(",".join("" if v is None else str(v) for v in row) + "\n")
    return len(rows)


# ── periodic sensor snapshot + settings sync ──

def _parse_int(raw):
    if raw is None:
        return None
    try:
        return int(float(str(raw).split(":")[-1].strip()))
    except (ValueError, AttributeError):
        return None


def log_sensor_snapshot() -> None:
    with _lock, _connect() as conn:
        conn.execute(
            """INSERT INTO sensor_log
               (ts, drive_mode, laser, us0, us1, photo, uv, metal, ball,
                lf_left, lf_mid, lf_right, motion, bus_v, cur_ma, bat_pct)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                time.strftime("%Y-%m-%d %H:%M:%S"),
                getattr(state.drive_mode, "value", str(state.drive_mode)),
                _parse_int(state.laserValue),
                _parse_int(state.ultrasonic0Value),
                _parse_int(state.ultrasonic1Value),
                _parse_int(state.photoValue),
                _parse_int(state.uvValue),
                _parse_int(state.metalValue),
                _parse_int(state.ballSwitchValue),
                _parse_int(state.lfLeftValue),
                _parse_int(state.lfMidValue),
                _parse_int(state.lfRightValue),
                _parse_int(state.motionValue),
                state.bus_v, state.cur_ma, state.bat_pct,
            ),
        )


def _sync_settings() -> None:
    set_setting("drive_scheme", state.drive_scheme)
    set_setting("voice_mode", state.voice_mode.name)
    set_setting("wheel_trim", state.wheel_trim)
    if isinstance(state.motorSpeedValue, int):
        set_setting("motor_speed", state.motorSpeedValue)


def _loop() -> None:
    while not _stop_event.is_set():
        try:
            log_sensor_snapshot()
            _sync_settings()
        except Exception as e:
            print(f"⚠️ kida_db periodic logging error: {e}")
        _stop_event.wait(SNAPSHOT_INTERVAL_S)


def start_periodic_logging() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="KidaDBLogger")
    _thread.start()
    print("💾 DB sensor/settings logging started")


def stop_periodic_logging() -> None:
    _stop_event.set()
    if _thread:
        _thread.join(timeout=2.0)
