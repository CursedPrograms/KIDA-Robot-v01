"""fleet_bt.py - Bluetooth as equal as WiFi: a robot's whole web API over Bluetooth serial.

The same file in every repo that uses it (like fleet_ladder.py): RIFT/Fleet is the master copy.
The ESP32 robots' side is RIFT/Fleet/esp32/fleet_bt.h. Standard library only (pyserial for COM ports).

One line per request, exactly what would be asked over WiFi:

    >GET /web?cmd=drive&f=1&l=0&t=0
    >POST /command<TAB>{"command": "forward"}

    >GET :5000/robots                     (another of the robot's ports: NORA's fleet list)

answered with   <code> <length>\\n<body: that many bytes>

so every command works the same both ways, including ones added later, and the robot's own rules
(the PIN, its stops) hold. Over Bluetooth the controller is "127.0.0.1" to the robot. This is the
fleet's one Bluetooth protocol: every robot speaks it, NORA too.

Controllers:
    link = BtHttp("COM7")                 # Windows: the port the paired robot got
    link = BtHttp("/dev/rfcomm0")         # Linux, bound with rfcomm
    link = BtHttp("B8:27:EB:12:34:56")    # straight to its address (RFCOMM channel 1; Windows and Linux)
    code, text = link.get("/status")
    code, text = link.post("/command", {"command": "forward"})
    link.close()

    session = BtSession("COM7", home_port=5002)   # or a drop-in for the requests.Session a controller uses:
    session.get("http://nora:5002/sensors").json()   # the path counts, and the port if it isn't home_port
    session.get("http://nora:5000/robots")           # -> ">GET :5000/robots" (it reconnects by itself)

The Pi robots (KIDA-00, KIDA-01):
    serve_rfcomm(5003)                    # a daemon thread: RFCOMM channel 1 -> http://127.0.0.1:5003
    (bluetoothctl: discoverable on, pairable on; the user pairs once)

    python fleet_bt.py COM7 /status       # try one from the command line
"""

import json
import socket
import sys
import threading
import urllib.error
import urllib.request

CHANNEL = 1          # RFCOMM: the ESP32's serial profile and the Pi server both listen here
MAX_BODY = 1 << 20
MAC_CHARS = set("0123456789abcdefABCDEF:")


def _is_mac(target):
    return len(target) == 17 and target.count(":") == 5 and set(target) <= MAC_CHARS


# ── The wire: the same both ways ──────────────────────────────────────────────

def request_line(method, path, body=None):
    if body is not None and not isinstance(body, str):
        body = json.dumps(body)
    line = f">{method.upper()} {path}" + (f"\t{body}" if body else "")
    if "\n" in line:
        raise ValueError("a request is one line")
    return (line + "\n").encode("utf-8")


def read_answer(read, raw=False):
    """read(n) -> up to n bytes. Returns (code, text), or (code, bytes) with raw=True (pictures)."""
    head = b""
    while not head.endswith(b"\n"):
        c = read(1)
        if not c:
            raise ConnectionError("the robot hung up")
        head += c
        if len(head) > 64:
            raise ConnectionError(f"not a fleet_bt answer: {head!r}")
    code, length = head.decode().split()
    length = int(length)
    if length > MAX_BODY:
        raise ConnectionError("answer too long")
    body = b""
    while len(body) < length:
        chunk = read(length - len(body))
        if not chunk:
            raise ConnectionError("the robot hung up mid-answer")
        body += chunk
    return int(code), body if raw else body.decode("utf-8", "replace")


# ── Controllers ───────────────────────────────────────────────────────────────

NUS_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"   # Bluetooth LE: the Nordic UART service (fleet_bt_ble.h)
NUS_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"


class _BleStream:
    """The same lines over Bluetooth LE (robots with BLE only: ARIA). `who`: her name or address. pip install bleak."""

    def __init__(self, who, timeout):
        import asyncio
        from bleak import BleakClient, BleakScanner
        self.timeout = timeout
        self._buf = bytearray()
        self._cv = threading.Condition()
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True, name="fleet-bt-ble").start()

        async def connect():
            dev = who if _is_mac(who) else await BleakScanner.find_device_by_name(who, timeout=timeout)
            if dev is None:
                raise ConnectionError(f"no Bluetooth LE device called {who}")
            client = BleakClient(dev)
            await client.connect(timeout=timeout)
            await client.start_notify(NUS_TX, self._heard)
            return client

        self._client = self._run(connect(), timeout + 5)

    def _run(self, coro, timeout):
        import asyncio
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    def _heard(self, _char, data):
        with self._cv:
            self._buf += data
            self._cv.notify_all()

    def write(self, data):
        for i in range(0, len(data), 180):        # BLE writes come in pieces
            self._run(self._client.write_gatt_char(NUS_RX, data[i:i + 180], response=True), self.timeout)

    def read(self, n):
        with self._cv:
            if not self._cv.wait_for(lambda: self._buf, timeout=self.timeout):
                return b""
            out = bytes(self._buf[:n])
            del self._buf[:n]
            return out

    def close(self):
        try:
            self._run(self._client.disconnect(), 3)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)


class BtHttp:
    """A robot's web API over Bluetooth: get() / post() like over WiFi. One request at a time.
    target: a COM port / /dev/rfcommN, a Classic address (RFCOMM channel 1), or "ble:<name or address>"."""

    def __init__(self, target, timeout=5.0):
        self.target = target
        self.timeout = timeout
        self._lock = threading.Lock()
        self._sock = self._ser = self._ble = None
        if target.lower().startswith("ble:"):
            self._ble = _BleStream(target[4:], timeout)
        elif _is_mac(target):
            self._sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
            self._sock.settimeout(timeout)
            self._sock.connect((target, CHANNEL))
        else:
            import serial   # pip install pyserial
            self._ser = serial.Serial(target, 115200, timeout=timeout)

    def _write(self, data):
        if self._ble:
            return self._ble.write(data)
        (self._sock.sendall if self._sock else self._ser.write)(data)

    def _read(self, n):
        if self._ble:
            return self._ble.read(n)
        return self._sock.recv(n) if self._sock else self._ser.read(n)

    def request(self, method, path, body=None, raw=False):
        with self._lock:
            self._write(request_line(method, path, body))
            return read_answer(self._read, raw)

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, body=None):
        return self.request("POST", path, body)

    def close(self):
        try:
            (self._ble or self._sock or self._ser).close()
        except Exception:
            pass


class _Answer:
    """What requests' Response gives the controllers: status_code, text, json(), headers."""

    def __init__(self, code, content):
        self.status_code, self.content = code, content     # .content: the bytes (pictures); .text: decoded
        self.text = content.decode("utf-8", "replace")
        self.ok = 200 <= code < 400
        self.headers = {"content-type": "application/json" if self.text[:1] in "{[" else "text/plain"}

    def json(self):
        return json.loads(self.text)


def _link_error(e):
    try:
        import requests
        return requests.exceptions.ConnectionError(str(e))
    except ImportError:
        return ConnectionError(str(e))


class BtSession:
    """A drop-in for requests.Session over Bluetooth, so a controller's own code doesn't change:
    session.get(f"{base}/status", params=..., timeout=...) -> .status_code / .json() / .text.
    Only the path and query of the URL are used. It reconnects by itself after a dropped link;
    a failure raises requests' ConnectionError, which the controllers already catch."""

    def __init__(self, target, timeout=5.0, home_port=None):
        self.target, self.timeout = target, timeout
        self.home_port = home_port      # a URL on another port than this goes as ":<port>/path"
        self._link = None
        self._lock = threading.Lock()

    def _path(self, url, params):
        from urllib.parse import urlencode, urlsplit
        u = urlsplit(url)
        path = (u.path or "/") + (f"?{u.query}" if u.query else "")
        if params:
            path += ("&" if "?" in path else "?") + urlencode(params)
        if u.port and self.home_port and u.port != self.home_port:
            path = f":{u.port}{path}"
        return path

    def _do(self, method, url, params=None, body=None):
        with self._lock:
            try:
                if self._link is None:
                    self._link = BtHttp(self.target, self.timeout)
                code, content = self._link.request(method, self._path(url, params), body, raw=True)
                return _Answer(code, content)
            except Exception as e:
                if self._link:
                    self._link.close()
                self._link = None
                raise _link_error(e) from e

    def get(self, url, params=None, timeout=None, **_):
        return self._do("GET", url, params)

    def post(self, url, params=None, json=None, data=None, timeout=None, **_):
        body = json if json is not None else data
        if isinstance(body, dict) and json is None:     # form data, as requests would send it
            from urllib.parse import urlencode
            body = urlencode(body)
        return self._do("POST", url, params, body)

    def close(self):
        with self._lock:
            if self._link:
                self._link.close()
            self._link = None


# ── The Pi robots: RFCOMM -> their own web server ─────────────────────────────

def answer_request(line, port, host="127.0.0.1"):
    """One request line (without the '>') asked of the robot's own web server. Returns the answer bytes."""
    line = line.strip()
    method, _, rest = line.partition(" ")
    path, _, body = rest.partition("\t")
    if path.startswith(":") and "/" in path:            # ":5000/robots": another of its ports
        p, path = path[1:].split("/", 1)
        port, path = (int(p) if p.isdigit() else port), "/" + path
    if not path.startswith("/"):
        code, raw = 400, b"bad path"
    else:
        data = body.encode("utf-8") if method.upper() == "POST" else None
        req = urllib.request.Request(f"http://{host}:{port}{path}", data=data, method=method.upper())
        if data is not None:
            req.add_header("Content-Type", "application/json" if body.startswith("{") else "application/x-www-form-urlencoded")
        try:
            with urllib.request.urlopen(req, timeout=4) as r:
                code, raw = r.status, r.read()          # the bytes as they are: pictures too
        except urllib.error.HTTPError as e:
            code, raw = e.code, e.read()
        except Exception as e:
            code, raw = 502, f"no answer from its web server: {e}".encode()
    return f"{code} {len(raw)}\n".encode() + raw


def serve_stream(read, write, port):
    """Answer one controller's requests until it hangs up. read(n) / write(bytes)."""
    line, mine = b"", False
    while True:
        c = read(1)
        if not c:
            return
        if c == b"\n":
            if mine:
                write(answer_request(line.decode("utf-8", "replace"), port))
            line, mine = b"", False
        elif c == b">" and not line and not mine:
            mine = True
        elif mine and c != b"\r" and len(line) < 4096:
            line += c


def wifi_rssi():
    """This computer's WiFi signal in dBm (Linux: /proc/net/wireless), or 0 if it can't tell."""
    try:
        with open("/proc/net/wireless") as f:
            for line in f.readlines()[2:]:
                parts = line.split()
                if len(parts) > 3:
                    return int(float(parts[3]))
    except (OSError, ValueError):
        pass
    return 0


def make_pairable(name=None):
    """Linux (the Pis): show up as `name`, discoverable and pairable, so a controller can pair once."""
    import subprocess
    cmds = ([["bluetoothctl", "system-alias", name]] if name else []) + \
           [["bluetoothctl", "power", "on"], ["bluetoothctl", "discoverable-timeout", "0"],
            ["bluetoothctl", "discoverable", "on"], ["bluetoothctl", "pairable", "on"]]
    for c in cmds:
        try:
            subprocess.run(c, capture_output=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            return False
    return True


def serve_rfcomm(port, channel=CHANNEL):
    """A daemon thread: Bluetooth controllers, one at a time, to http://127.0.0.1:<port>."""
    def run():
        try:
            srv = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
            srv.bind((socket.BDADDR_ANY if hasattr(socket, "BDADDR_ANY") else "00:00:00:00:00:00", channel))
            srv.listen(1)
        except (OSError, AttributeError) as e:
            print(f"[fleet_bt] no Bluetooth serial ({e}): WiFi only")
            return
        print(f"[fleet_bt] Bluetooth serial on RFCOMM {channel} -> :{port}")
        while True:
            conn, addr = srv.accept()
            print(f"[fleet_bt] controller {addr[0]} connected")
            try:
                serve_stream(conn.recv, conn.sendall, port)
            except OSError:
                pass
            finally:
                conn.close()
                print(f"[fleet_bt] controller {addr[0]} left")
    t = threading.Thread(target=run, daemon=True, name="fleet-bt")
    t.start()
    return t


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("python fleet_bt.py <COMx | /dev/rfcommN | MAC> <path> [json body]")
    link = BtHttp(sys.argv[1])
    try:
        code, text = link.post(sys.argv[2], sys.argv[3]) if len(sys.argv) > 3 else link.get(sys.argv[2])
        print(code, text)
    finally:
        link.close()
