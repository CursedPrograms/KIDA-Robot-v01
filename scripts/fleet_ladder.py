"""fleet_ladder.py - the fleet's WiFi ladder, for the programs that run on a computer.

The same file in every repo that uses it (like peer_talk.py): RIFT/Fleet is the master copy.
Standard library only, so it drops into DREAM, NINA, TINA, the controllers and the KIDAs as is.

The rule (fleet TODO, section 2): everyone joins the highest network it can see above itself;
with none, it hosts its own, named after itself, plus the fleet list on :5000 (/ping, /register,
/robots, RIFT's wire format), so the ones below find each other. Every CHECK_S it looks again:
still connected? Is the host still answering? Is a higher one back? It moves up when one is.

    RIFT                                                   the hub
    > DREAM > NINA > TINA                                  the virtual bots
    > NORACTL > WHIPCTL > KIDA01CTL > KIDA00CTL > ARMCTL   the PC controllers, in their bots' order
    > NORA > WHIP > KIDA01 > KIDA00 > ARM > MILA           the real bots

Several programs on one computer share one WiFi card, so only the highest one running there
drives it (they see each other through small files in the temp folder); the rest just ride along.

Linux (Pis, Kubuntu): NetworkManager's nmcli; the hotspot is 192.168.4.1, channel 1, like the
robots'. It needs the rights to change the WiFi (root, or a polkit rule for the user).
Windows: netsh to join, the Mobile Hotspot to host (192.168.137.1; the PC keeps its own WiFi).

    ladder = FleetLadder("DREAM", enabled=True)
    ladder.start()                       # a daemon thread; ladder.stop() ends it (and the hotspot)
    ladder.registry_host()               # where to POST /register now: the network's host
    ladder.status()                      # for a status page

Off unless asked (enabled=True, or FLEET_LADDER=1): it takes over the computer's WiFi.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs
from urllib.request import urlopen

LADDER = ["RIFT",
          "DREAM", "NINA", "TINA",
          "NORACTL", "WHIPCTL", "KIDA01CTL", "KIDA00CTL", "ARMCTL",
          "NORA", "WHIP", "KIDA01", "KIDA00", "ARM", "MILA"]
FLEET_PASSWORD = "mmvbkbak"        # the fleet's, the same as every robot's secrets.h
REGISTRY_PORT = 5000
CHECK_S = 15                       # look around this often
LOST_CHECKS = 3                    # the network (or its host) gone this many checks running: climb again
LOCAL_FRESH_S = 3 * CHECK_S        # a program on this computer counts as running for this long
FLEET_TTL_S = 20                   # the fleet list drops a robot after this long without a heartbeat
AP_CON = "fleet-ladder-ap"         # nmcli's name for the hotspot connection
WINDOWS = sys.platform.startswith("win")


def rank(name):
    """Place on the ladder (0 = RIFT), or None if it isn't on it."""
    return LADDER.index(name) if name in LADDER else None


def _sh(args, timeout=30):
    """Run a command; (exit code, output). Never raises."""
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                           creationflags=0x08000000 if WINDOWS else 0)   # CREATE_NO_WINDOW
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


# ── The WiFi, per system ──────────────────────────────────────────────────────

class NmcliWifi:
    """NetworkManager (Linux)."""

    def __init__(self, sh=_sh):
        self.sh = sh
        self.ifname = None

    def _dev(self):
        if not self.ifname:
            _, out = self.sh(["nmcli", "-t", "-f", "DEVICE,TYPE", "device"])
            self.ifname = next((l.split(":")[0] for l in out.splitlines() if l.endswith(":wifi")), "wlan0")
        return self.ifname

    def scan(self):
        _, out = self.sh(["nmcli", "-t", "-f", "SSID", "device", "wifi", "list", "--rescan", "yes"])
        return {l.strip() for l in out.splitlines() if l.strip()}

    def connected(self):
        _, out = self.sh(["nmcli", "-t", "-f", "ACTIVE,SSID", "device", "wifi"])
        return next((l[4:] for l in out.splitlines() if l.startswith("yes:")), None)

    def hosting(self):
        _, out = self.sh(["nmcli", "-t", "-f", "NAME", "connection", "show", "--active"])
        return AP_CON in out.splitlines()

    def join(self, ssid, password):
        self.stop_hosting()
        code, out = self.sh(["nmcli", "device", "wifi", "connect", ssid, "password", password,
                             "ifname", self._dev()], timeout=45)
        return code == 0, out.strip()

    def host(self, ssid, password):
        self.sh(["nmcli", "connection", "delete", AP_CON])
        code, out = self.sh(["nmcli", "connection", "add", "type", "wifi", "ifname", self._dev(),
                             "con-name", AP_CON, "autoconnect", "no", "ssid", ssid,
                             "802-11-wireless.mode", "ap", "802-11-wireless.band", "bg",
                             "802-11-wireless.channel", "1",
                             "ipv4.method", "shared", "ipv4.addresses", "192.168.4.1/24",
                             "wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password])
        if code == 0:
            code, out = self.sh(["nmcli", "connection", "up", AP_CON], timeout=45)
        return code == 0, out.strip()

    def stop_hosting(self):
        self.sh(["nmcli", "connection", "down", AP_CON])

    def gateway(self):
        _, out = self.sh(["ip", "-4", "route", "show", "default", "dev", self._dev()])
        m = re.search(r"via (\d+\.\d+\.\d+\.\d+)", out)
        return m.group(1) if m else None


_WIN_TETHER = r"""
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$ops = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 }
function Await($op, $type) {
  $m = ($ops | Where-Object { $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0].MakeGenericMethod($type)
  $t = $m.Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
function AwaitAction($op) {
  $m = ($ops | Where-Object { $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' })[0]
  $t = $m.Invoke($null, @($op)); $t.Wait(-1) | Out-Null }
$p = [Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime]::GetInternetConnectionProfile()
if (-not $p) { $p = [Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime]::GetConnectionProfiles() | Select-Object -First 1 }
if (-not $p) { 'no network to share from'; exit 2 }
$tm = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime]::CreateFromConnectionProfile($p)
$rt = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime]
switch ('%ACTION%') {
  'state' { "$($tm.TetheringOperationalState)|$($tm.GetCurrentAccessPointConfiguration().Ssid)" }
  'start' {
    $c = $tm.GetCurrentAccessPointConfiguration(); $c.Ssid = '%SSID%'; $c.Passphrase = '%PW%'
    AwaitAction ($tm.ConfigureAccessPointAsync($c))
    $r = Await ($tm.StartTetheringAsync()) $rt; "$($r.Status) $($r.AdditionalErrorMessage)"
    if ($r.Status -ne 'Success') { exit 1 } }
  'stop' { $r = Await ($tm.StopTetheringAsync()) $rt; "$($r.Status)" }
}
"""


class NetshWifi:
    """Windows: netsh to join, the Mobile Hotspot (WinRT, through powershell.exe) to host."""

    def __init__(self, sh=_sh):
        self.sh = sh
        self.my_ssid = None

    def _tether(self, action, ssid="", password=""):
        script = (_WIN_TETHER.replace("%ACTION%", action)
                  .replace("%SSID%", ssid.replace("'", "")).replace("%PW%", password.replace("'", "")))
        return self.sh(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], timeout=60)

    def scan(self):
        _, out = self.sh(["netsh", "wlan", "show", "networks"])
        return {m.group(1).strip() for m in re.finditer(r"^SSID \d+ : (.*)$", out, re.M) if m.group(1).strip()}

    def connected(self):
        _, out = self.sh(["netsh", "wlan", "show", "interfaces"])
        if not re.search(r"^\s*State\s*: connected", out, re.M):
            return None
        m = re.search(r"^\s*SSID\s*: (.+)$", out, re.M)
        return m.group(1).strip() if m else None

    def hosting(self):
        _, out = self._tether("state")
        state, _, ssid = out.strip().partition("|")
        return state == "On" and (self.my_ssid is None or ssid == self.my_ssid)

    def join(self, ssid, password):
        self.stop_hosting()
        xml = f"""<?xml version="1.0"?>
<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">
  <name>{ssid}</name><SSIDConfig><SSID><name>{ssid}</name></SSID></SSIDConfig>
  <connectionType>ESS</connectionType><connectionMode>auto</connectionMode>
  <MSM><security><authEncryption><authentication>WPA2PSK</authentication><encryption>AES</encryption>
  <useOneX>false</useOneX></authEncryption><sharedKey><keyType>passPhrase</keyType>
  <protected>false</protected><keyMaterial>{password}</keyMaterial></sharedKey></security></MSM>
</WLANProfile>"""
        path = os.path.join(tempfile.gettempdir(), f"fleet-ladder-{ssid}.xml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(xml)
        try:
            self.sh(["netsh", "wlan", "add", "profile", f"filename={path}", "user=current"])
        finally:
            try:
                os.remove(path)       # it holds the password
            except OSError:
                pass
        code, out = self.sh(["netsh", "wlan", "connect", f"name={ssid}", f"ssid={ssid}"])
        return code == 0, out.strip()

    def host(self, ssid, password):
        self.my_ssid = ssid
        code, out = self._tether("start", ssid, password)
        return code == 0, out.strip()

    def stop_hosting(self):
        if self.my_ssid:
            self._tether("stop")

    def gateway(self):
        _, out = self.sh(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                          "(Get-NetIPConfiguration | Where-Object { $_.NetAdapter.PhysicalMediaType -match '802.11' -and "
                          "$_.IPv4DefaultGateway }).IPv4DefaultGateway.NextHop | Select-Object -First 1"])
        m = re.search(r"\d+\.\d+\.\d+\.\d+", out)
        return m.group(0) if m else None


# ── The fleet list, while hosting ─────────────────────────────────────────────

class FleetRegistry:
    """/ping, /register, /robots on :5000: the same wire format as RIFT's and NORA's."""

    def __init__(self, name, port=REGISTRY_PORT):
        self.name, self.port = name, port
        self.robots, self.lock = {}, threading.Lock()
        self.server = None

    def roster(self):
        now = time.time()
        with self.lock:
            for n in [n for n, r in self.robots.items() if now - r["last_seen"] > FLEET_TTL_S]:
                del self.robots[n]
            return [{"name": n, "ip": r["ip"], "type": r["type"], "capabilities": r["capabilities"]}
                    for n, r in self.robots.items()]

    def start(self):
        if self.server:
            return True
        reg = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, code, body, ctype="text/plain"):
                data = body.encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path.startswith("/ping"):
                    self._send(200, f"{reg.name} alive")
                elif self.path.startswith("/robots"):
                    self._send(200, json.dumps({"authority": reg.name, "robots": reg.roster()}), "application/json")
                else:
                    self._send(404, "not found")

            def do_POST(self):
                if not self.path.startswith("/register"):
                    return self._send(404, "not found")
                form = parse_qs(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode(errors="ignore"))
                name = (form.get("name") or [""])[0]
                if not name:
                    return self._send(400, "missing name")
                with reg.lock:
                    reg.robots[name] = {"ip": self.client_address[0], "type": (form.get("type") or ["unknown"])[0],
                                        "capabilities": [c for c in (form.get("capabilities") or [""])[0].split(",") if c],
                                        "last_seen": time.time()}
                self._send(200, "OK")

            def log_message(self, *a):
                pass

        try:
            self.server = ThreadingHTTPServer(("0.0.0.0", self.port), Handler)
        except OSError:
            return False          # something already serves :5000 here (RIFT itself): fine, it's the list
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True, name="fleet-registry").start()
        return True

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None


# ── The ladder ────────────────────────────────────────────────────────────────

class FleetLadder:
    def __init__(self, name, enabled=None, password=FLEET_PASSWORD, wifi=None, log=print,
                 local_dir=None, check_s=CHECK_S, ping=None):
        if rank(name) is None:
            raise ValueError(f"{name} isn't on the ladder: {LADDER}")
        if enabled is None:
            enabled = os.environ.get("FLEET_LADDER", "") in ("1", "true", "yes")
        self.name, self.enabled, self.password = name, bool(enabled), password
        self.wifi = wifi or (NetshWifi() if WINDOWS else NmcliWifi())
        self.log, self.check_s = log, check_s
        self.local_dir = local_dir or os.path.join(tempfile.gettempdir(), "dream-fleet-ladder")
        self.ping = ping or self._ping
        self.registry = FleetRegistry(name)
        self.state = "off" if not self.enabled else "starting"   # hosting / joined / riding / alone / off
        self.network, self.lost, self.note = None, 0, ""
        self._stop = threading.Event()
        self._thread = None

    # -- what the program asks --
    def registry_host(self):
        """Where the fleet list is now: here while hosting, else the network's host. None = don't know."""
        if self.state == "hosting":
            return "127.0.0.1"
        if self.state in ("joined", "riding"):
            return self.wifi.gateway()
        return None

    def status(self):
        return {"name": self.name, "enabled": self.enabled, "state": self.state, "network": self.network,
                "lost_checks": self.lost, "note": self.note}

    def start(self):
        if not self.enabled or self._thread:
            return self
        self._thread = threading.Thread(target=self._run, daemon=True, name="fleet-ladder")
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        self._unmark()
        if self.state == "hosting":
            self.wifi.stop_hosting()
        self.registry.stop()

    # -- the programs on this computer --
    def _mark(self):
        try:
            os.makedirs(self.local_dir, exist_ok=True)
            with open(os.path.join(self.local_dir, self.name), "w") as f:
                f.write(str(time.time()))
        except OSError:
            pass

    def _unmark(self):
        try:
            os.remove(os.path.join(self.local_dir, self.name))
        except OSError:
            pass

    def _local_top(self):
        """The highest program running on this computer (myself included)."""
        best, now = self.name, time.time()
        try:
            for n in os.listdir(self.local_dir):
                if rank(n) is None:
                    continue
                try:
                    with open(os.path.join(self.local_dir, n)) as f:
                        fresh = now - float(f.read().strip() or 0) < LOCAL_FRESH_S
                except (OSError, ValueError):
                    fresh = False
                if fresh and rank(n) < rank(best):
                    best = n
        except OSError:
            pass
        return best

    @staticmethod
    def _ping(host):
        try:
            with urlopen(f"http://{host}:{REGISTRY_PORT}/ping", timeout=3) as r:
                return r.status == 200
        except Exception:
            return False

    # -- one look around --
    def check(self):
        self._mark()
        me = rank(self.name)
        top = self._local_top()
        if top != self.name:                      # a higher program here drives the WiFi
            if self.state == "hosting":
                self.wifi.stop_hosting()
                self.registry.stop()
            self.state, self.note = "riding", f"{top} runs the WiFi on this computer"
            self.network = self.wifi.connected()
            return self.state

        seen = self.wifi.scan()
        above = sorted((n for n in seen if rank(n) is not None and rank(n) < me), key=rank)
        best = above[0] if above else None
        on = self.wifi.connected()

        if self.state == "hosting" or self.wifi.hosting():
            if best:                              # someone higher showed up: move up to them
                self.log(f"[ladder] {best} is up: stop hosting, join it")
                self.registry.stop()
                return self._join(best)
            self.registry.start()                 # keep hosting; the list stays up
            self.state, self.network, self.lost = "hosting", self.name, 0
            return self.state

        if on and rank(on) is not None and rank(on) < me:   # on a ladder network above me
            alive = on in seen or not seen
            gw = self.wifi.gateway()
            if alive and gw and self.ping(gw):
                self.lost = 0
            else:
                self.lost += 1                    # still connected? its host still answering?
            if best and rank(best) < rank(on):
                self.log(f"[ladder] {best} ranks above {on}: moving up")
                return self._join(best)
            if self.lost >= LOST_CHECKS:
                self.log(f"[ladder] {on} gone or silent {self.lost} checks: climbing again")
                self.lost = 0
                return self._join(best) if best and best != on else self._host()
            self.state, self.network = "joined", on
            return self.state

        if best:                                  # on nothing, or on a network off the ladder
            return self._join(best)
        return self._host()                       # nobody above me around: I'm the host

    def _join(self, ssid):
        ok, out = self.wifi.join(ssid, self.password)
        self.lost = 0
        if ok:
            self.state, self.network, self.note = "joined", ssid, ""
        else:
            self.state, self.network, self.note = "alone", None, f"join {ssid} failed: {out[-200:]}"
            self.log(f"[ladder] {self.note}")
        return self.state

    def _host(self):
        ok, out = self.wifi.host(self.name, self.password)
        if ok:
            self.registry.start()
            self.state, self.network, self.note = "hosting", self.name, ""
            self.log(f"[ladder] nobody above {self.name} around: hosting \"{self.name}\" and the fleet list on :{REGISTRY_PORT}")
        else:
            self.state, self.network, self.note = "alone", None, f"hosting failed: {out[-200:]}"
            self.log(f"[ladder] {self.note}")
        return self.state

    def _run(self):
        while not self._stop.is_set():
            try:
                self.check()
            except Exception as e:                # never take the program down with it
                self.note = f"check failed: {e}"
            self._stop.wait(self.check_s)


if __name__ == "__main__":
    # python fleet_ladder.py NAME          one look, and what it would do (nothing changes)
    # python fleet_ladder.py NAME --run    run it for real, until Ctrl+C
    import argparse
    ap = argparse.ArgumentParser(description="The fleet's WiFi ladder")
    ap.add_argument("name", choices=LADDER[1:])
    ap.add_argument("--run", action="store_true", help="take over the WiFi and keep climbing")
    a = ap.parse_args()
    w = NetshWifi() if WINDOWS else NmcliWifi()
    if not a.run:
        seen = w.scan()
        above = sorted((n for n in seen if rank(n) is not None and rank(n) < rank(a.name)), key=rank)
        print(f"on: {w.connected()}  hosting: {w.hosting()}  gateway: {w.gateway()}")
        print(f"ladder networks in sight: {sorted((n for n in seen if rank(n) is not None), key=rank)}")
        print(f"{a.name} would " + (f"join {above[0]}" if above else f"host \"{a.name}\""))
    else:
        lad = FleetLadder(a.name, enabled=True).start()
        try:
            while True:
                time.sleep(5)
                print(lad.status())
        except KeyboardInterrupt:
            lad.stop()
