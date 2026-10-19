# small_screen.py — KIDA-01's big-text screen for the small touch screen in her HDMI 1 port
#
# Her main HUD (ui.py) is far too detailed for a little screen, so this shows a
# few things at arm's length instead: her face, what mode she's in, whether her
# wheels are locked, battery and temperature, and what she's doing.
#
# It runs as its own program next to the HUD (pygame opens one window per
# program), reading her state from her own web server on this Pi (/status and
# /mind on port 5004), so it never touches the motors, the cameras or the HUD.
# main.py starts it by itself (launch() below); it closes when main.py does.
#
# Screens go by the Pi's HDMI port: HDMI 0 is the desktop screen (the HUD, ui.py), HDMI 1 the
# small touch screen (this). The port is read from /sys/class/drm (HDMI-A-1 = HDMI 0, HDMI-A-2 =
# HDMI 1), so it doesn't matter which screens are plugged in: SDL only numbers the connected ones.
#
# config.json, under "Config" (all optional):
#   "SmallScreen": {"Enabled": true, "Port": 1}
#     Enabled  false = never start it
#     Port     the HDMI port the small screen is in (0 or 1)
#     Display  off a Pi (no /sys/class/drm): which screen, counted from 0
#
# On its own, for trying it out:   python3 scripts/small_screen.py [--port 1] [--window]
# With no screen in that port it waits, looking again every 15 s.

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

ROBOT_URL = "http://127.0.0.1:5004"
POLL_S    = 1.0      # how often her state is read
RETRY_S   = 15.0     # how often to look for the screen while it isn't there
_HERE     = os.path.dirname(os.path.abspath(__file__))
_ROOT     = os.path.dirname(_HERE)

BG      = (8, 10, 18)
TEXT    = (240, 236, 245)
DIM     = (130, 136, 155)
ACCENT  = (236, 72, 153)     # her pink
GREEN   = (70, 220, 130)
RED     = (240, 80, 90)
AMBER   = (245, 180, 60)

MODE_NAMES = {
    "KEYBOARD": "DRIVING", "IR_REMOTE": "IR REMOTE", "AUTONOMOUS": "EXPLORING",
    "LINE_FOLLOWER": "LINE FOLLOW", "IDLE": "ASLEEP", "WATCHDOG": "ON WATCH",
    "LANE_DETECT": "LANE FOLLOW", "PERSON_FOLLOW": "FOLLOWING",
}


def settings() -> dict:
    cfg = {"Enabled": True, "Port": 1, "Display": 1}
    try:
        with open(os.path.join(_ROOT, "config.json"), encoding="utf-8") as f:
            cfg.update(json.load(f)["Config"].get("SmallScreen", {}))
    except (OSError, ValueError, KeyError):
        pass
    return cfg


def hdmi_connected():
    """{0: bool, 1: bool}: is a screen plugged into the Pi's HDMI 0 / HDMI 1? None off a Pi."""
    import glob
    ports, seen = {0: False, 1: False}, False
    for n in (0, 1):
        for path in glob.glob(f"/sys/class/drm/card*-HDMI-A-{n + 1}/status"):
            seen = True
            try:
                with open(path) as f:
                    ports[n] = ports[n] or f.read().strip() == "connected"
            except OSError:
                pass
    return ports if seen else None


def display_index(port, fallback=None):
    """SDL's screen number for the screen in HDMI <port>: SDL counts only connected screens,
    in port order. -1 if that port is empty; `fallback` off a Pi (no DRM connectors)."""
    ports = hdmi_connected()
    if ports is None:
        return fallback
    if not ports.get(port):
        return -1
    return sum(1 for p in range(port) if ports[p])


def launch() -> None:
    """Called by main.py: starts this screen as its own program, unless config.json
    turns it off. Never raises: the robot runs the same without it."""
    try:
        cfg = settings()
        if not cfg.get("Enabled", True):
            return
        subprocess.Popen([sys.executable, os.path.abspath(__file__),
                          "--port", str(int(cfg.get("Port", 1))),
                          "--display", str(int(cfg.get("Display", 1))),
                          "--parent", str(os.getpid())])
        print(f"🖥️  Small screen: looking for a screen in HDMI {cfg.get('Port', 1)}")
    except Exception as e:
        print(f"⚠️ Small screen not started: {e}")


# ── her state, read in the background ─────────────────────────────────────────
class Robot:
    def __init__(self):
        self.status = {}
        self.mind = {}
        self.online = False
        threading.Thread(target=self._poll, daemon=True).start()

    @staticmethod
    def _get(path):
        with urllib.request.urlopen(ROBOT_URL + path, timeout=2) as r:
            return json.loads(r.read().decode("utf-8"))

    def _poll(self):
        while True:
            try:
                self.status = self._get("/status")
                self.online = True
            except Exception:
                self.online = False
            try:
                self.mind = self._get("/mind")
            except Exception:
                self.mind = {}
            time.sleep(POLL_S)


def doing(status: dict, mind: dict) -> str:
    """One short line: what she's up to right now."""
    if mind.get("sleeping"):
        return "Sleeping"
    person = status.get("person") or mind.get("person")
    for text in (mind.get("doing_alone"), mind.get("thought")):
        if text:
            return f"With {person}: {text}" if person else text
    if person:
        return f"With {person}"
    mood = (mind.get("mood") or {}).get("label")
    if mood:
        return f"Feeling {mood}"
    return "Playing music" if status.get("music_on") else ""


# ── drawing ───────────────────────────────────────────────────────────────────
def round_face(pygame, path, size):
    """Her avatar as a circle, or None."""
    try:
        img = pygame.image.load(path).convert()
    except (pygame.error, FileNotFoundError):
        return None
    s = min(img.get_size())
    img = img.subsurface(((img.get_width() - s) // 2, (img.get_height() - s) // 2, s, s))
    img = pygame.transform.smoothscale(img, (size, size))
    out = pygame.Surface((size, size), pygame.SRCALPHA)
    mask = pygame.Surface((size, size), pygame.SRCALPHA)
    pygame.draw.circle(mask, (255, 255, 255, 255), (size // 2, size // 2), size // 2)
    out.blit(img, (0, 0))
    out.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    return out


_fonts = {}


def font(pygame, size, bold=False):
    """Fonts are looked up once per size: SysFont searches the system each time."""
    key = (size, bold)
    if key not in _fonts:
        _fonts[key] = pygame.font.SysFont("DejaVu Sans,Arial", size, bold=bold)
    return _fonts[key]


def fit(pygame, text, max_w, size, bold=True):
    """The biggest font up to `size` that fits text in max_w pixels."""
    while size > 10:
        f = font(pygame, size, bold)
        if f.size(text)[0] <= max_w:
            return f
        size = int(size * 0.9)
    return font(pygame, 10, bold)


def wrap(font, text, width, max_lines):
    """Up to max_lines lines that fit in width; the last one ends in … if the text goes on."""
    lines, words = [], text.split()
    while words and len(lines) < max_lines:
        line = words.pop(0)
        while words and font.size(f"{line} {words[0]}")[0] <= width:
            line += " " + words.pop(0)
        lines.append(line)
    if words and lines:
        last = lines[-1]
        while last and font.size(last + "…")[0] > width:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return lines


def draw(pygame, screen, face, robot, frame):
    W, H = screen.get_size()
    screen.fill(BG)
    st, mind = robot.status, robot.mind
    pad = max(8, H // 30)

    if not robot.online:
        f = fit(pygame, "Waiting for KIDA…", W - 2 * pad, H // 8)
        s = f.render("Waiting for KIDA…", True, DIM)
        screen.blit(s, s.get_rect(center=(W // 2, H // 2)))
        return

    # Wide screens: face on the left, text on the right. Tall or square ones: face on top.
    wide = W >= H * 1.25
    if wide:
        fs = min(H - 2 * pad, W // 3)
        face_pos = (pad, (H - fs) // 2)
        x0, tw, y = pad * 2 + fs, W - fs - pad * 3, pad
    else:
        fs = min(W - 2 * pad, H // 3)
        face_pos = ((W - fs) // 2, pad)
        x0, tw, y = pad, W - 2 * pad, pad * 2 + fs
    if face is not None:
        if face.get_width() != fs:
            face = pygame.transform.smoothscale(face, (fs, fs))
        screen.blit(face, face_pos)
        ring = ACCENT if not mind.get("sleeping") else DIM
        pygame.draw.circle(screen, ring, (face_pos[0] + fs // 2, face_pos[1] + fs // 2), fs // 2 + 2, max(2, fs // 60))

    rows_h = H - y - pad
    big = max(14, rows_h // 4)

    # 1. Mode — the biggest thing on the screen
    mode = MODE_NAMES.get(st.get("mode", ""), str(st.get("mode", "?")).replace("_", " "))
    f = fit(pygame, mode, tw, big)
    screen.blit(f.render(mode, True, TEXT), (x0, y))
    y += f.get_linesize()

    # 2. Wheels — red when locked, green when free
    locked = bool(st.get("motor_lock"))
    wheels = "WHEELS LOCKED" if locked else "WHEELS FREE"
    f = fit(pygame, wheels, tw, int(big * 0.7))
    screen.blit(f.render(wheels, True, RED if locked else GREEN), (x0, y))
    y += f.get_linesize()

    # 3. Battery and temperature, when she reports them
    parts = []
    bat = st.get("bat_pct")
    if isinstance(bat, (int, float)) and bat > 0:
        parts.append((f"{int(bat)}%", RED if bat < 20 else AMBER if bat < 40 else GREEN))
    temp = st.get("cpu_temp")
    try:
        t = float(str(temp).replace("°C", "").replace("C", "").strip())
        parts.append((f"{t:.0f}°C", RED if t >= 75 else AMBER if t >= 65 else TEXT))
    except (TypeError, ValueError):
        pass
    if parts:
        f = fit(pygame, "   ".join(p for p, _ in parts), tw, int(big * 0.6))
        x = x0
        for text, colour in parts:
            s = f.render(text, True, colour)
            screen.blit(s, (x, y))
            x += s.get_width() + f.size("   ")[0]
        y += f.get_linesize()

    # 4. What she's doing, in what's left (up to 3 lines)
    line = doing(st, mind)
    if line and y < H - pad:
        f = font(pygame, max(12, int(big * 0.42)))
        for text in wrap(f, line, tw, max(1, min(3, (H - pad - y) // f.get_linesize()))):
            screen.blit(f.render(text, True, DIM), (x0, y))
            y += f.get_linesize()


# ── main ──────────────────────────────────────────────────────────────────────
def parent_alive(pid):
    if not pid or os.name == "nt":      # on Windows, os.kill(pid, 0) would send Ctrl+C instead
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def main():
    ap = argparse.ArgumentParser(description="KIDA-01's big-text screen for a small display")
    ap.add_argument("--port", type=int, default=settings().get("Port", 1), help="HDMI port (0 or 1)")
    ap.add_argument("--display", type=int, default=settings().get("Display", 1), help="off a Pi: screen number")
    ap.add_argument("--window", action="store_true", help="a 480x320 window instead (testing)")
    ap.add_argument("--parent", type=int, default=0, help="close when this process ends (main.py)")
    args = ap.parse_args()

    os.environ.setdefault("SDL_VIDEO_ALLOW_SCREENSAVER", "1")
    import pygame

    # Wait for the screen (HDMI 1 may be empty, or plugged in later)
    while True:
        pygame.display.init()
        sizes = pygame.display.get_desktop_sizes()
        index = display_index(args.port, args.display)
        if args.window or 0 <= index < len(sizes):
            break
        pygame.display.quit()
        if not parent_alive(args.parent):
            return
        time.sleep(RETRY_S)

    pygame.font.init()
    if args.window:
        screen = pygame.display.set_mode((480, 320))
    else:
        screen = pygame.display.set_mode(sizes[index], pygame.FULLSCREEN, display=index)
        pygame.mouse.set_visible(False)
    pygame.display.set_caption("KIDA-01 small screen")

    face_path = os.path.join(_ROOT, "images", "kida_avatar.jpeg")
    face = round_face(pygame, face_path, 512)
    robot = Robot()
    clock = pygame.time.Clock()
    frame = 0
    while parent_alive(args.parent):
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE and args.window):
                return
        draw(pygame, screen, face, robot, frame)
        pygame.display.flip()
        frame += 1
        clock.tick(4)          # it's a status board: 4 frames a second is plenty


if __name__ == "__main__":
    main()
