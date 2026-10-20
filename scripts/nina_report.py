# nina_report.py — every 15 s her state and her distance sensors to NINA, the fleet's caretaker
# (fleet TODO §4 and §7, as KIDA-00 does it). NINA runs on RIFT's PC on :5012, so nothing is sent
# until a RIFT is found over Zeroconf (_rift._tcp). NINA watches the readings: one stuck on the same
# value gets a checkup.
#
#   POST http://<RIFT's PC>:5012/report
#   {"name": "KIDA01", "state": {"moving", "turning", "wheels_locked", "music", "mode"},
#    "sensors": {"US0": 23.5, "US1": 40.0}}          (cm; what she has no reading for is left out)

import re
import socket
import threading
import time

import requests

NAME = "KIDA01"
NINA_PORT = 5012
REPORT_S = 15
RIFT_TYPE = "_rift._tcp.local."

rift_servers: dict = {}   # name -> "http://ip:port"


class _RiftListener:
    def remove_service(self, zc, type_, name):
        rift_servers.pop(name.split('.')[0], None)

    def add_service(self, zc, type_, name):
        self.update_service(zc, type_, name)

    def update_service(self, zc, type_, name):
        info = zc.get_service_info(type_, name)
        if info and info.addresses:
            rift_servers[name.split('.')[0]] = f"http://{socket.inet_ntoa(info.addresses[0])}:{info.port}"


def _cm(value):
    """'ULTRASONIC0:8', 'US0: 23.5 cm', '23.5' or 23.5 -> the number; '-', 'N/A' -> None.
    The number after the label's colon, so the 0 in "US0" isn't read as the distance."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    m = re.search(r"-?\d+(?:\.\d+)?", str(value or "").rsplit(":", 1)[-1])
    return float(m.group(0)) if m else None


def body() -> dict:
    import state
    import mode_manager
    import web_bridge
    try:
        import odometry
        moving = bool(odometry.summary().get("moving"))
        turning = (getattr(odometry, "_left", 0) or 0) * (getattr(odometry, "_right", 0) or 0) < 0
    except Exception:
        moving = turning = False
    sensors = {k: _cm(getattr(state, attr, None)) for k, attr in
               (("US0", "ultrasonic0Value"), ("US1", "ultrasonic1Value"))}
    return {"name": NAME,
            "state": {"moving": moving, "turning": turning,
                      "wheels_locked": bool(getattr(state, "motor_lock", False)),
                      "music": "playing" if web_bridge.music_playing() else "stopped",
                      "mode": mode_manager.current_mode().name},
            "sensors": {k: v for k, v in sensors.items() if v is not None}}


def _loop():
    session = requests.Session()
    while True:
        time.sleep(REPORT_S)
        rift = next(iter(rift_servers.values()), "")
        if not rift:
            continue
        try:
            session.post(f"{rift.rsplit(':', 1)[0]}:{NINA_PORT}/report", json=body(), timeout=2)
        except Exception:
            pass   # NINA isn't up, or a reading went odd: try again next time


def start(zeroconf):
    """Browse for RIFT on server.py's Zeroconf and start reporting."""
    from zeroconf import ServiceBrowser
    ServiceBrowser(zeroconf, RIFT_TYPE, _RiftListener())
    threading.Thread(target=_loop, daemon=True, name="nina-report").start()
