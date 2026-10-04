# fleet_register.py — announces this KIDA instance to the RIFT/NORA fleet registry
#
# NORA (https://github.com/CursedPrograms/NORA-Robot-v00) is the network's
# always-on node at a fixed address, hosting the fleet registry (/register,
# /robots on port 5000) that RIFT (https://github.com/CursedPrograms/RIFT)
# reads from and can claim authority over. This mirrors RIFT's own
# Fleet/register.py client pattern exactly, so KIDA shows up as a first-class
# fleet member (name, type, capabilities) rather than just a bare mDNS peer.
#
# Safe to start even if NORA isn't reachable (different network, still
# booting, etc.) — it just keeps retrying on the same interval and never
# raises.

import threading
import time

import requests

NORA_HOST = "192.168.4.1"   # NORA's fixed WiFi AP address
NORA_PORT = 5000            # NORA's fleet-registry port
HEARTBEAT_SECS = 10         # must stay under NORA's FLEET_TTL_MS (20s) or the entry flaps


def _announce(host, port, name, capabilities):
    try:
        requests.post(
            f"http://{host}:{port}/register",
            data={
                "name": name,
                "type": "robot",
                "capabilities": ",".join(capabilities),
            },
            timeout=2,
        )
        return True
    except requests.RequestException:
        return False


def start_fleet_heartbeat(name, capabilities=None,
                           host=NORA_HOST, port=NORA_PORT,
                           interval=HEARTBEAT_SECS):
    """
    Start a background heartbeat thread that repeatedly registers this
    KIDA instance with NORA's fleet registry. Returns the daemon thread;
    it never returns on its own so there's normally no need to join() it.
    """
    capabilities = capabilities or [
        "camera", "object_detection", "voice_assistant",
        "autonomous_drive", "sensors",
        "talk:5004",   # RIFT's conversations: /chirp?u= on server.py's port
    ]

    def _loop():
        while True:
            _announce(host, port, name, capabilities)
            time.sleep(interval)

    t = threading.Thread(target=_loop, daemon=True, name="fleet-heartbeat")
    t.start()
    return t
