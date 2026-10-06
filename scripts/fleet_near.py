"""
fleet_near.py - who's nearby, over Bluetooth LE, and making way for them.

The fleet's ESP32 robots (NORA, WHIP) find each other over ESP-NOW and BLE; a
Pi can't do ESP-NOW, but its built-in Bluetooth does BLE. So a Pi robot (the
KIDAs, or RIFT when it runs on a Pi):

  advertises  the fleet's "I'm here" beacon - manufacturer data, company id
              0xFFFF, then "DRFL", version 1, its state (one byte: parked /
              driving / yielding / user) and its name
  scans       for everyone else's, and keeps for each robot a smoothed signal
              strength, its trend (coming closer / steady / leaving) and what
              it says it's doing

    above -45 dBm  very close      -45 .. -60  near
    -60 .. -75     medium          below -75   far

Avoiding each other - the same rules as NORA's and WHIP's fleet_near.h:
  it's parked       -> we're closing in because of me: I steer away
  it's yielding     -> it's making way: carry on, carefully
  a human drives it -> unpredictable: I make way
  it drives itself  -> the alphabet decides (KIDA00 first ... WHIP last);
                       everyone makes way for MILA, who can't hear the others
  coming closer     -> act sooner;   leaving -> no need to make way

    near = FleetNear("KIDA01").start()
    near.set_state("driving")          # "parked" / "driving" / "user"
    near.advice()                      # "clear" / "caution" / "yield"
    near.give_way(can_turn=True)       # "go" / "wait" / "turn": do this now
    near.snapshot()                    # nearest first

Coarse by nature (walls, bodies, antennas): for "who's around", not distance.
Needs bleak (pip) to listen. To be heard it needs BlueZ's bluetoothctl (every
Pi OS); on Windows (RIFT on a PC) it only listens.
"""

import asyncio
import shutil
import subprocess
import threading
import time

COMPANY = 0xFFFF
MAGIC = b"DRFL\x01"
STATES = ("parked", "driving", "yielding", "user")
FORGET_S = 5.0
FRESH_S = 2.0
CAUTION_RSSI, YIELD_RSSI = -60, -45
TREND_DBS = 1.5


def zone(rssi):
    if rssi > -45:
        return "very close"
    if rssi > -60:
        return "near"
    if rssi > -75:
        return "medium"
    return "far"


def trend(rate):
    return "approaching" if rate > TREND_DBS else "leaving" if rate < -TREND_DBS else "steady"


class FleetNear:
    def __init__(self, name, state="parked"):
        self.name = name[:11]
        self.state = state
        self._peers = {}        # name -> {"rssi", "seen", "state", "rate", "then_rssi", "then_t"}
        self._lock = threading.Lock()
        self._adv = None
        self._adv_state = None
        self.problem = None
        self._phase, self._phase_until, self._quiet_until, self._yield_to = "go", 0.0, 0.0, ""

    def start(self):
        threading.Thread(target=self._scan_thread, daemon=True, name="fleet-near-scan").start()
        self._advertise()
        return self

    # ---------------------------------------------------------------- being heard
    def my_state(self):
        return "yielding" if self._phase != "go" else self.state

    def set_state(self, state):
        """What this robot is doing: "parked", "driving" or "user"."""
        self.state = state if state in STATES else "driving"
        if self.my_state() != self._adv_state:
            self._advertise()

    def _advertise(self):
        """BlueZ drops an advertisement when the program that registered it exits, so
        bluetoothctl stays running; a new state re-registers the advert."""
        if not shutil.which("bluetoothctl"):
            return                    # Windows, or no BlueZ: listen only
        st = self.my_state()
        data = " ".join(f"0x{b:02x}" for b in MAGIC + bytes([STATES.index(st)]) + self.name.encode()[:11])
        try:
            if self._adv is None or self._adv.poll() is not None:
                self._adv = subprocess.Popen(["bluetoothctl"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL, text=True)
                self._adv.stdin.write("power on\n")
            else:
                self._adv.stdin.write("advertise off\n")
            self._adv.stdin.write(f"menu advertise\nclear\nmanufacturer 0x{COMPANY:04x} {data}\ninterval 500 600\nback\n"
                                  f"advertise broadcast\n")
            self._adv.stdin.flush()   # stdin stays open: closing it would end bluetoothctl and the beacon
            self._adv_state = st
        except (OSError, ValueError, BrokenPipeError) as e:
            self.problem = f"can't advertise: {e}"
            self._adv = None

    # ---------------------------------------------------------------- hearing the others
    def _heard(self, device, adv):
        md = adv.manufacturer_data.get(COMPANY)
        if not md or not md.startswith(MAGIC) or len(md) < len(MAGIC) + 2:
            return
        st = md[len(MAGIC)]
        name = md[len(MAGIC) + 1:].split(b"\x00")[0].decode("utf-8", "ignore")[:11]
        if not name or name == self.name:
            return
        now = time.time()
        with self._lock:
            p = self._peers.get(name)
            if p is None or now - p["seen"] > FORGET_S:
                p = {"rssi": adv.rssi, "rate": 0.0, "then_rssi": adv.rssi, "then_t": now}
            else:
                p["rssi"] = 0.7 * p["rssi"] + 0.3 * adv.rssi        # like fleet_near.h
                if now - p["then_t"] >= 1.0:                          # the trend, dB/s over ~1 s, smoothed
                    inst = (p["rssi"] - p["then_rssi"]) / (now - p["then_t"])
                    p["rate"] = 0.7 * p["rate"] + 0.3 * inst
                    p["then_rssi"], p["then_t"] = p["rssi"], now
            p["seen"], p["state"] = now, STATES[st] if st < len(STATES) else "driving"
            self._peers[name] = p

    def _scan_thread(self):
        try:
            from bleak import BleakScanner
        except ImportError:
            self.problem = "bleak isn't installed (pip install bleak)"
            print(f"[near] {self.problem} - no Bluetooth proximity")
            return

        async def run():
            async with BleakScanner(detection_callback=self._heard):
                while True:
                    await asyncio.sleep(3600)

        while True:
            try:
                asyncio.run(run())
            except Exception as e:          # no adapter, adapter busy, BlueZ restarted...
                if self.problem != str(e):
                    self.problem = str(e)
                    print(f"[near] Bluetooth scan stopped ({e}); retrying in 30 s")
                time.sleep(30)

    # ---------------------------------------------------------------- what's near
    def snapshot(self):
        now = time.time()
        with self._lock:
            for k in [k for k, p in self._peers.items() if now - p["seen"] > FORGET_S]:
                del self._peers[k]
            items = sorted(self._peers.items(), key=lambda kv: -kv[1]["rssi"])
        return [{"name": k, "rssi": round(p["rssi"]), "zone": zone(p["rssi"]), "state": p["state"],
                 "trend": trend(p["rate"]), "rate_dbs": round(p["rate"], 1), "via": "ble",
                 "age_ms": int((now - p["seen"]) * 1000)} for k, p in items]

    def nearest(self):
        s = [r for r in self.snapshot() if r["age_ms"] < FRESH_S * 1000]
        return s[0] if s else None

    # ---------------------------------------------------------------- making way
    def advice(self):
        """"clear", "caution" or "yield" - the same rules as fleet_near.h."""
        p = self.nearest()
        if p is None:
            return "clear"
        coming, going = p["rate_dbs"] > TREND_DBS, p["rate_dbs"] < -TREND_DBS
        if p["state"] == "yielding":
            my_turn = False
        elif p["state"] in ("parked", "user"):
            my_turn = True
        else:
            my_turn = p["name"] == "MILA" or self.name > p["name"]
        yield_at = CAUTION_RSSI if coming else YIELD_RSSI
        caution_at = -75 if coming else CAUTION_RSSI
        if p["rssi"] > yield_at and my_turn and not going:
            return "yield"
        return "caution" if p["rssi"] > caution_at else "clear"

    def give_way(self, can_turn=True):
        """Call each control step of a self-driving mode: "wait" (stop), "turn" (turn away) or "go"."""
        now = time.time()
        if self._phase == "wait" and now >= self._phase_until:
            if can_turn:
                self._phase, self._phase_until = "turn", now + 0.6
            else:
                self._phase, self._quiet_until = "go", now + 4.0
        elif self._phase == "turn" and now >= self._phase_until:
            self._phase, self._quiet_until = "go", now + 5.0
        if self._phase == "go" and now >= self._quiet_until and self.advice() == "yield":
            n = self.nearest()
            self._phase, self._phase_until, self._yield_to = "wait", now + 2.0, n["name"] if n else ""
        if self.my_state() != self._adv_state:
            self._advertise()       # the others hear "yielding" straight away
        return self._phase

    def status(self):
        n = self.nearest()
        return {"self": self.name, "state": self.my_state(), "advice": self.advice(), "nearest": n["name"] if n else "",
                "yielding_to": self._yield_to if self._phase != "go" else "", "radio": "bluetooth le",
                "problem": self.problem, "robots": self.snapshot()}
