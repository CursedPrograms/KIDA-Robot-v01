"""controller_kit.py - what every robot's PC controller shares.

The same file in every robot's repo (like mind.py and gamepad_drive.py): change one, copy it to the
others. Fleet TODO section 13 lists who has it.

    colours = theme_colours("DEFAULT")     # ../colour_scheme.xml (from the avatar): DEFAULT / LIGHT / CUSTOM
    settings = Settings()                  # scripts/controller_settings.json: the theme, CUSTOM's colours
    fit(text, font, width)                 # cut to fit, with "..."
    pending = Pending()                    # settings re-sent until the robot's status says so:
    pending.want("mode", 1, send)          #   sends now, then again every RESEND_S...
    pending.check(status, at)              #   ...until status["mode"] == 1 or GIVE_UP_S went by
                                           #   (at: when that status was asked for, so an old one can't confirm it)
    pending.value("mode")                  # what was just picked (show it before the robot confirms)
    keys_vector(pressed, KEYS)             # held keys -> (forward, side, turn), -1..1 each: W+A is both
    FakeRobot                              # a pretend robot's web server for EMULATE (fake_<robot>.py)
    voice = Voice("Microsoft David Desktop", LINES)   # the robot talking through this PC's speakers:
    voice.say("wall")                      #   a random line for that event, not too often, one at a time
"""

import json
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEME_XML = os.path.join(HERE, "..", "colour_scheme.xml")
SETTINGS_JSON = os.path.join(HERE, "controller_settings.json")   # per PC, not in git
THEMES = ["DEFAULT", "LIGHT", "CUSTOM"]
RESEND_S = 0.6     # a setting the robot hasn't confirmed is sent again this often...
GIVE_UP_S = 6.0    # ...until its status says so, or this long has gone by

# colour_scheme.xml's names, if the file can't be read (a neutral dark scheme)
SCHEME_FALLBACK = {
    "background": "#080A12", "panel": "#0E1120", "border": "#1D223F", "divider": "#15192E",
    "text": "#F2E9EA", "text_sec": "#A89497", "text_dim": "#6B575A", "accent": "#D34859",
    "accent_hover": "#DA6473", "accent2": "#1A7BD9", "accent3": "#CC4A82",
    "button_hover_bg": "#250E11", "danger_bg": "#210F0D",
}


# ---- colours: always from colour_scheme.xml ----

def rgb(v):
    v = v.lstrip("#")
    return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def load_scheme(path=SCHEME_XML):
    """colour_scheme.xml as {name: "#RRGGBB"} (its format: name="..." value="#RRGGBB")."""
    try:
        with open(path, encoding="utf-8") as f:
            found = dict(re.findall(r'name="([^"]+)"\s+value="(#[0-9A-Fa-f]{6})"', f.read()))
    except OSError:
        found = {}
    return {**SCHEME_FALLBACK, **found}


def theme_colours(name, custom=None):
    """The scheme's colours as RGB, for DEFAULT (as it is), LIGHT (its accents on light surfaces made
    from its own text colours) or CUSTOM (custom's "#RRGGBB" values over it)."""
    c = {k: rgb(v) for k, v in load_scheme().items()}
    if name == "LIGHT":
        white = (255, 255, 255)
        c.update(background=c["text"], panel=mix(c["text"], white, 0.7), border=mix(c["text"], c["text_sec"], 0.45),
                 divider=mix(c["text"], c["text_sec"], 0.18), text=c["background"], text_sec=c["text_dim"],
                 text_dim=c["text_sec"], button_hover_bg=mix(c["accent"], white, 0.82),
                 danger_bg=mix(c["accent"], white, 0.88))
    elif name == "CUSTOM":
        c.update({k: rgb(v) for k, v in (custom or {}).items()
                  if isinstance(v, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", v)})
    return c


class Settings(dict):
    """scripts/controller_settings.json: {"theme": ..., "custom": {...}}. save() never raises."""

    def __init__(self, path=SETTINGS_JSON):
        super().__init__()
        self.path = path
        try:
            with open(path, encoding="utf-8") as f:
                self.update(json.load(f))
        except (OSError, ValueError):
            pass

    @property
    def theme(self):
        return self.get("theme") if self.get("theme") in THEMES else "DEFAULT"

    def next_theme(self):
        """DEFAULT -> LIGHT -> CUSTOM. The first CUSTOM writes the scheme's colours into "custom" for
        you to change. Returns the theme's colours."""
        self["theme"] = THEMES[(THEMES.index(self.theme) + 1) % len(THEMES)]
        if self["theme"] == "CUSTOM" and not self.get("custom"):
            self["custom"] = load_scheme()
        self.save()
        return theme_colours(self["theme"], self.get("custom"))

    def colours(self):
        return theme_colours(self.theme, self.get("custom"))

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(dict(self), f, indent=2)
        except OSError:
            pass


def fit(text, font, width):
    """text, cut short with "..." if it's wider than width in this font."""
    if font.size(text)[0] <= width:
        return text
    while text and font.size(text + "...")[0] > width:
        text = text[:-1]
    return text + "..."


# ---- settings that stick ----

class Pending:
    """Settings sent again until the robot's status confirms them: a robot busy mid-move can miss a
    one-shot request, and the controller then snapped back to the old value."""

    def __init__(self):
        self._want = {}   # key -> [value, send, first, last]

    def want(self, key, value, send):
        send()
        now = time.monotonic()
        self._want[key] = [value, send, now, now]

    def value(self, key):
        w = self._want.get(key)
        return None if w is None else w[0]

    def check(self, status, at=None):
        """at: time.monotonic() when this status was asked for. A status asked for before the
        setting was picked still shows the old state (or a value from before that), so it can't
        confirm it: without at, every status counts."""
        now = time.monotonic()
        for key in list(self._want):
            value, send, first, last = self._want[key]
            got = status.get(key)
            try:
                same = got is not None and float(got) == float(value)
            except (TypeError, ValueError):
                same = got == value
            if (same and (at is None or at >= first)) or now - first > GIVE_UP_S:
                del self._want[key]
            elif now - last > RESEND_S:
                send()
                self._want[key][3] = now


# ---- driving: held keys blend ----

def keys_vector(pressed, keys):
    """Held keys -> (forward, side, turn), each -1..1, so two at once blend: W+A is forward AND left.
    keys: {"fwd": (...), "back": (...), "left": (...), "right": (...), "turn_l": (...), "turn_r": (...)},
    each a tuple of pygame key codes; side and turn are + to the left (anticlockwise)."""
    def held(name):
        return any(pressed[k] for k in keys.get(name, ()))
    return (held("fwd") - held("back"), held("left") - held("right"), held("turn_l") - held("turn_r"))


# ---- a voice through this PC's speakers ----

class Voice:
    """The robot talking through this PC, outside MIND mode too: say(event) speaks a random line
    from lines[event] ({...} filled from fmt), at most once every COOLDOWN_S for the same event and
    one line at a time (a line that comes in while another is spoken waits; a third replaces it).
    Windows: its own text-to-speech (mind.windows_say, the voices the robots' lines are made with);
    Linux / macOS: spd-say or espeak if they're there. on = False keeps it quiet."""

    COOLDOWN_S = 8.0

    def __init__(self, voice, lines, rate=0, pitch="medium"):
        self.voice, self.rate, self.pitch, self.lines = voice, rate, pitch, lines
        self.on = True
        self.said = ""                 # the last line, for the window
        self._last = {}                # event -> when it last spoke
        self._next = None              # the line waiting its turn
        self._wake = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def say(self, event, **fmt):
        now = time.monotonic()
        if not self.on or event not in self.lines or now - self._last.get(event, -1e9) < self.COOLDOWN_S:
            return
        self._last[event] = now
        self._next = random.choice(self.lines[event]).format(**fmt)
        self._wake.set()

    def _run(self):
        while True:
            self._wake.wait()
            self._wake.clear()
            text, self._next = self._next, None
            if text and self.on:
                self.said = text
                self._speak(text)
                if self._next:
                    self._wake.set()

    def _speak(self, text):
        try:
            if sys.platform == "win32":
                import mind   # the same file in every controller
                mind.windows_say(text, self.voice, self.rate, self.pitch)
            elif shutil.which("spd-say"):
                subprocess.run(["spd-say", "-w", text], timeout=30)
            elif shutil.which("espeak"):
                subprocess.run(["espeak", text], timeout=30)
        except Exception:
            pass   # no voice on this PC: the line still shows in the window


# ---- EMULATE: a pretend robot's web server ----

class FakeRobot:
    """A pretend robot for EMULATE: serves route(port, path, query) -> (code, body[, content_type]) on
    host:port, steps a pretend world 20 times a second (step(dt)), and keeps a log of what it did
    (log() / LOG). Subclass it in fake_<robot>.py with that robot's own routes.
    body: a dict / list (JSON), text, bytes (an image), or a generator of bytes (streamed: a camera).
    GET and POST both come to route(); a POST's body is q["_body"], and q["_json"] if it's JSON."""

    NAME = "ROBOT"
    PORTS = (5000,)

    def __init__(self, host="127.0.0.1"):
        self.lock = threading.Lock()
        self.LOG = deque(maxlen=50)
        self.quiet = False
        self._stop = threading.Event()
        self._servers = []
        robot = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self._reply({})

            def do_POST(self):   # the body as q["_body"] (bytes), and q["_json"] if it's a JSON object
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                extra = {"_body": raw}
                try:
                    obj = json.loads(raw or b"null")
                    if isinstance(obj, dict):
                        extra["_json"] = obj
                except ValueError:
                    pass
                self._reply(extra)

            def _reply(self, extra):
                url = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(url.query).items()}
                q.update(extra)
                with robot.lock:
                    res = robot.route(self.server.server_address[1], url.path, q)
                code, body = res[0], res[1]
                ctype = res[2] if len(res) > 2 else None
                try:
                    if hasattr(body, "__next__"):   # a generator: streamed (an MJPEG camera), outside the lock
                        self.send_response(code)
                        self.send_header("Content-Type", ctype or "application/octet-stream")
                        self.end_headers()
                        for chunk in body:
                            if robot._stop.is_set():
                                break
                            self.wfile.write(chunk)
                            self.wfile.flush()
                        return
                    if isinstance(body, bytes):
                        data, ctype = body, ctype or "application/octet-stream"
                    elif isinstance(body, (dict, list)):
                        data, ctype = json.dumps(body).encode(), ctype or "application/json"
                    else:
                        data, ctype = str(body).encode(), ctype or "text/plain"
                    self.send_response(code)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except (ConnectionError, OSError):
                    pass   # the controller hung up (a stream it stopped reading)

        class Server(ThreadingHTTPServer):
            allow_reuse_address = False   # on Windows a second fake would share the port silently

        try:
            for port in self.PORTS:
                self._servers.append(Server((host, port), Handler))
        except OSError:
            for s in self._servers:
                s.server_close()
            raise
        for s in self._servers:
            threading.Thread(target=s.serve_forever, daemon=True).start()
        threading.Thread(target=self._world, daemon=True).start()

    def _world(self):
        last = time.monotonic()
        while not self._stop.wait(0.05):
            now = time.monotonic()
            with self.lock:
                self.step(now - last)
            last = now

    def log(self, msg):
        if not self.LOG or self.LOG[-1].split(" ", 1)[1] != msg:
            self.LOG.append(f"{time.strftime('%H:%M:%S')} {msg}")
            if not self.quiet:
                print(f"{time.strftime('%H:%M:%S')} {self.NAME} {msg}", flush=True)

    def last_log(self):
        return self.LOG[-1] if self.LOG else "booted"

    def stop(self):
        self._stop.set()
        for s in self._servers:
            s.shutdown()
            s.server_close()

    # override these
    def route(self, port, path, q):
        return 404, "not found"

    def step(self, dt):
        pass
