"""
options.py - a game-style options menu for this bot's config.json.

The same file sits in every bot's repo: it reads whatever config.json is next
to it, shows each section as a menu, and edits the values in place. Colours
come from the bot's colour_scheme.xml and the avatar from images/, so every
bot's options screen looks like that bot.

    python options.py                 edits ./config.json (and settings.json if it has anything)
    python options.py other.json      edits another file

Keys:  Up/Down pick   Enter open / toggle / edit   Left/Right change a value
       (Shift = 10x)  Esc back   Ctrl+S save   Ctrl+Z revert   mouse works too
Values: on/off for true/false, < 12 > for numbers, typing for text, and a
fixed list wherever options_choices.json names the choices, e.g.
    {"Config/DREAM/DreamImageModel": ["auto", "sd-turbo", "sdxl-turbo"]}
Saving keeps the old file as config.json.bak.
"""

import copy
import glob
import json
import os
import re
import shutil
import sys

import pygame

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 900, 640
ROW_H = 44
TOP = 120
BOTTOM = 70
FPS = 60

DEFAULT_COLOURS = {
    "background": "#070A12", "panel": "#0D1221", "border": "#192543", "divider": "#121A30",
    "text": "#E9ECF2", "text_sec": "#949BA8", "text_dim": "#575E6B",
    "accent": "#4C8DFF", "accent_hover": "#89B4FF", "accent2": "#4F73D9",
    "button_hover_bg": "#0E1625", "danger_bg": "#210F0D",
}


# ---------------------------------------------------------------- the bot's look
def load_colours():
    colours = dict(DEFAULT_COLOURS)
    try:
        with open(os.path.join(HERE, "colour_scheme.xml"), encoding="utf-8") as f:
            for name, value in re.findall(r'name="([^"]+)"\s+value="(#[0-9A-Fa-f]{6})"', f.read()):
                colours[name] = value
    except OSError:
        pass
    return {k: pygame.Color(v) for k, v in colours.items()}


def load_avatar(size):
    pics = [p for p in glob.glob(os.path.join(HERE, "images", "*")) if "avatar" in os.path.basename(p).lower()
            and p.lower().endswith((".png", ".jpg", ".jpeg"))]
    if not pics:
        return None
    try:
        img = pygame.transform.smoothscale(pygame.image.load(pics[0]).convert(), (size, size))
    except pygame.error:
        return None
    mask = pygame.Surface((size, size), pygame.SRCALPHA)
    pygame.draw.circle(mask, (255, 255, 255, 255), (size // 2, size // 2), size // 2)
    out = pygame.Surface((size, size), pygame.SRCALPHA)
    out.blit(img, (0, 0))
    out.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    return out


def bot_name(data, path):
    name = (data.get("Config", {}) if isinstance(data, dict) else {}).get("AppName")
    return (name or re.split(r"[-_]", os.path.basename(HERE))[0]).upper()   # ARM-Robot-v01 -> ARM


# ---------------------------------------------------------------- the files
class ConfigFile:
    def __init__(self, path):
        self.path = path
        with open(path, encoding="utf-8") as f:
            raw = f.read()
        self.data = json.loads(raw) if raw.strip() else {}
        m = re.search(r"\n( +)\"", raw)
        self.indent = len(m.group(1)) if m else 2
        self.saved = copy.deepcopy(self.data)

    @property
    def dirty(self):
        return self.data != self.saved

    def save(self):
        if os.path.exists(self.path):
            shutil.copy(self.path, self.path + ".bak")
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=self.indent, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, self.path)
        self.saved = copy.deepcopy(self.data)

    def revert(self):
        self.data = copy.deepcopy(self.saved)


def load_choices():
    try:
        with open(os.path.join(HERE, "options_choices.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def nice(key):
    """'LipsyncEnabled' -> 'Lipsync Enabled', 'rift_port' -> 'Rift Port'."""
    s = re.sub(r"[_\-]+", " ", str(key))
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", s)
    return s[:1].upper() + s[1:]


def step_for(value, big):
    if isinstance(value, int):
        return 10 if big else 1
    mag = abs(value) if value else 1.0
    step = 10 ** (len(str(int(mag))) - 2) if mag >= 10 else (0.1 if mag >= 1 else 0.01)
    return step * (10 if big else 1)


# ---------------------------------------------------------------- the menu
class Options:
    def __init__(self, files):
        pygame.init()
        pygame.key.set_repeat(350, 40)
        self.screen = pygame.display.set_mode((W, H))
        self.c = load_colours()
        self.files = files
        self.fi = 0
        self.path = []            # keys into the current file's data
        self.sel = 0
        self.scroll = 0
        self.editing = None       # (key, text) while typing a value
        self.message, self.message_t = "", 0
        self.choices = load_choices()
        self.f_title = pygame.font.SysFont("consolas,couriernew,monospace", 30, bold=True)
        self.f_row = pygame.font.SysFont("consolas,couriernew,monospace", 19)
        self.f_small = pygame.font.SysFont("consolas,couriernew,monospace", 15)
        self.avatar = load_avatar(72)
        self.name = bot_name(files[0].data, files[0].path)
        pygame.display.set_caption(f"{self.name} - Options")
        if self.avatar:
            pygame.display.set_icon(self.avatar)
        self.hit = []             # (rect, action) for the mouse
        self._quit_deadline = 0

    # -- data helpers
    @property
    def file(self):
        return self.files[self.fi]

    def node(self):
        n = self.file.data
        for k in self.path:
            n = n[k]
        return n

    def rows(self):
        n = self.node()
        return list(n.keys()) if isinstance(n, dict) else list(range(len(n)))

    def key_path(self, key):
        return "/".join(str(k) for k in self.path + [key])

    def set_value(self, key, value):
        self.node()[key] = value

    def say(self, text):
        self.message, self.message_t = text, pygame.time.get_ticks()

    # -- actions
    def activate(self, key):
        v = self.node()[key]
        if isinstance(v, (dict, list)) and not self._is_simple_list(v):
            self.path.append(key)
            self.sel, self.scroll = 0, 0
        elif isinstance(v, bool):
            self.set_value(key, not v)
        elif self.key_path(key) in self.choices:
            self.change(key, +1)
        else:
            self.editing = (key, v if isinstance(v, str) else json.dumps(v))

    @staticmethod
    def _is_simple_list(v):
        return isinstance(v, list) and all(not isinstance(x, (dict, list)) for x in v)

    def change(self, key, direction, big=False):
        v = self.node()[key]
        opts = self.choices.get(self.key_path(key))
        if opts:
            i = opts.index(v) if v in opts else -1
            self.set_value(key, opts[(i + direction) % len(opts)])
        elif isinstance(v, bool):
            self.set_value(key, not v)
        elif isinstance(v, (int, float)):
            nv = v + direction * step_for(v, big)
            self.set_value(key, int(nv) if isinstance(v, int) else round(nv, 6))

    def commit_edit(self):
        key, text = self.editing
        old = self.node()[key]
        if isinstance(old, str):
            self.set_value(key, text)
        else:
            try:
                new = json.loads(text)
                if isinstance(old, (int, float)) and not isinstance(new, (int, float)):
                    raise ValueError
                self.set_value(key, new)
            except ValueError:
                self.say(f"'{text}' isn't a valid {type(old).__name__} - kept {json.dumps(old)}")
        self.editing = None

    def back(self):
        if self.path:
            key = self.path.pop()
            rows = self.rows()
            self.sel = rows.index(key) if key in rows else 0
            return True
        return False

    def save(self):
        n = 0
        for f in self.files:
            if f.dirty:
                f.save()
                n += 1
        self.say(f"Saved {n} file(s). Restart {self.name} to use the new settings." if n else "Nothing to save.")

    def revert(self):
        self.file.revert()
        self.path, self.sel = [], 0
        self.say(f"Reverted {os.path.basename(self.file.path)}.")

    # -- drawing
    def text(self, s, font, colour, pos, max_w=None):
        if max_w is not None:
            while s and font.size(s)[0] > max_w:
                s = s[:-2] + "…" if len(s) > 2 else ""
        img = font.render(s, True, colour)
        self.screen.blit(img, pos)
        return img.get_rect(topleft=pos)

    def button(self, label, rect, action, hot=False, danger=False):
        mouse = pygame.Rect(rect).collidepoint(pygame.mouse.get_pos())
        fill = self.c["danger_bg"] if danger else (self.c["button_hover_bg"] if (mouse or hot) else self.c["panel"])
        pygame.draw.rect(self.screen, fill, rect, border_radius=6)
        pygame.draw.rect(self.screen, self.c["accent"] if (mouse or hot) else self.c["border"], rect, 1, border_radius=6)
        img = self.f_row.render(label, True, self.c["text"])
        self.screen.blit(img, img.get_rect(center=pygame.Rect(rect).center))
        self.hit.append((pygame.Rect(rect), action))

    def arrow(self, centre, direction, colour, size=6):
        """A filled triangle (the console fonts have no arrow glyphs)."""
        cx, cy = centre
        tip = cx + direction * size
        pygame.draw.polygon(self.screen, colour, [(tip, cy), (cx - direction * size, cy - size), (cx - direction * size, cy + size)])

    def value_widget(self, key, v, x, y, selected):
        right = W - 40
        opts = self.choices.get(self.key_path(key))
        if self.editing and self.editing[0] == key:
            box = pygame.Rect(x, y + 6, right - x, ROW_H - 12)
            pygame.draw.rect(self.screen, self.c["button_hover_bg"], box, border_radius=4)
            pygame.draw.rect(self.screen, self.c["accent"], box, 1, border_radius=4)
            t = self.editing[1]
            caret = "|" if (pygame.time.get_ticks() // 500) % 2 else " "
            shown = t
            while shown and self.f_row.size(shown + caret)[0] > box.w - 16:
                shown = shown[1:]
            self.text(shown + caret, self.f_row, self.c["text"], (box.x + 8, box.y + 5))
            return
        if isinstance(v, (dict, list)) and not self._is_simple_list(v):
            n = len(v)
            self.text(f"{n} item{'s' if n != 1 else ''}", self.f_row, self.c["text_sec"], (right - 160, y + 11))
            self.arrow((right - 10, y + ROW_H // 2), +1, self.c["accent"] if selected else self.c["text_sec"])
        elif isinstance(v, bool):
            r = pygame.Rect(right - 90, y + 9, 90, ROW_H - 18)
            pygame.draw.rect(self.screen, self.c["accent"] if v else self.c["panel"], r, border_radius=r.h // 2)
            pygame.draw.rect(self.screen, self.c["border"], r, 1, border_radius=r.h // 2)
            knob = r.h - 6
            kx = r.right - knob - 3 if v else r.x + 3
            pygame.draw.circle(self.screen, self.c["text"], (kx + knob // 2, r.centery), knob // 2)
            self.text("ON" if v else "OFF", self.f_small, self.c["text"] if v else self.c["text_dim"],
                      (r.x + 12 if v else r.right - 36, r.y + 5))
            self.hit.append((r, ("toggle", key)))
        elif isinstance(v, (int, float)) or opts:
            label = str(v) if not isinstance(v, float) else f"{v:g}"
            lw = 200
            lft = pygame.Rect(right - lw, y + 8, 28, ROW_H - 16)
            rgt = pygame.Rect(right - 28, y + 8, 28, ROW_H - 16)
            for r, a in ((lft, -1), (rgt, +1)):
                hot = r.collidepoint(pygame.mouse.get_pos())
                pygame.draw.rect(self.screen, self.c["button_hover_bg"] if hot else self.c["panel"], r, border_radius=4)
                self.arrow(r.center, a, self.c["accent"] if (selected or hot) else self.c["text_sec"])
                self.hit.append((r, ("change", key, a)))
            img = self.f_row.render(label, True, self.c["accent_hover"] if selected else self.c["text"])
            self.screen.blit(img, img.get_rect(center=((lft.right + rgt.x) // 2, y + ROW_H // 2)))
        else:
            s = v if isinstance(v, str) else json.dumps(v)
            s = s.replace("\n", " ↵ ")
            self.text(s if s else "(empty)", self.f_row, self.c["text"] if s else self.c["text_dim"], (x, y + 11), right - x)

    def draw(self):
        c, scr = self.c, self.screen
        self.hit = []
        scr.fill(c["background"])
        # header: avatar, name, which file and where in it
        x0 = 24
        if self.avatar:
            scr.blit(self.avatar, (24, 22))
            pygame.draw.circle(scr, c["accent"], (60, 58), 37, 2)
            x0 = 112
        self.text(f"{self.name}  OPTIONS", self.f_title, c["accent"], (x0, 26))
        crumbs = " › ".join([os.path.basename(self.file.path)] + [nice(k) for k in self.path])
        self.text(crumbs, self.f_small, c["text_sec"], (x0, 66), W - x0 - 24)
        # file tabs
        tx = x0
        for i, f in enumerate(self.files):
            label = os.path.basename(f.path) + (" *" if f.dirty else "")
            w = self.f_small.size(label)[0] + 20
            self.button_small(label, pygame.Rect(tx, 88, w, 24), ("file", i), i == self.fi)
            tx += w + 8
        pygame.draw.line(scr, c["divider"], (0, TOP - 4), (W, TOP - 4))

        rows = self.rows()
        visible = (H - TOP - BOTTOM) // ROW_H
        self.sel = max(0, min(self.sel, len(rows) - 1))
        if self.sel < self.scroll:
            self.scroll = self.sel
        elif self.sel >= self.scroll + visible:
            self.scroll = self.sel - visible + 1
        node = self.node()
        if not rows:
            self.text("(nothing in here)", self.f_row, c["text_dim"], (40, TOP + 12))
        for i, key in enumerate(rows[self.scroll:self.scroll + visible]):
            idx = self.scroll + i
            y = TOP + i * ROW_H
            r = pygame.Rect(16, y + 2, W - 32, ROW_H - 4)
            selected = idx == self.sel
            if selected:
                pygame.draw.rect(scr, c["button_hover_bg"], r, border_radius=6)
                pygame.draw.rect(scr, c["accent"], (16, y + 8, 4, ROW_H - 16), border_radius=2)
            self.hit.append((r, ("select", idx)))
            label = nice(key) if isinstance(key, str) else f"#{key + 1}"
            self.text(label, self.f_row, c["text"] if selected else c["text_sec"], (36, y + 11), 300)
            self.value_widget(key, node[key], 350, y, selected)
        if len(rows) > visible:   # scrollbar
            track = pygame.Rect(W - 12, TOP, 4, visible * ROW_H)
            pygame.draw.rect(scr, c["divider"], track)
            h = max(20, track.h * visible // len(rows))
            ty = track.y + (track.h - h) * self.scroll // max(1, len(rows) - visible)
            pygame.draw.rect(scr, c["accent2"], (track.x, ty, 4, h))

        # bottom bar
        pygame.draw.line(scr, c["divider"], (0, H - BOTTOM + 4), (W, H - BOTTOM + 4))
        by = H - BOTTOM + 18
        self.button("BACK" if self.path else "QUIT", (24, by, 110, 38), ("back",))
        self.button("REVERT", (W - 270, by, 110, 38), ("revert",))
        self.button("SAVE" + (" *" if any(f.dirty for f in self.files) else ""), (W - 146, by, 122, 38), ("save",),
                    hot=any(f.dirty for f in self.files))
        if self.message and pygame.time.get_ticks() - self.message_t < 5000:
            self.text(self.message, self.f_small, c["accent_hover"], (150, by + 10), W - 440)
        else:
            self.text("↑↓ pick  Enter open/edit  ←→ change  Esc back  Ctrl+S save",
                      self.f_small, c["text_dim"], (150, by + 10), W - 440)
        pygame.display.flip()

    def button_small(self, label, rect, action, active):
        c = self.c
        pygame.draw.rect(self.screen, c["button_hover_bg"] if active else c["panel"], rect, border_radius=5)
        pygame.draw.rect(self.screen, c["accent"] if active else c["border"], rect, 1, border_radius=5)
        img = self.f_small.render(label, True, c["text"] if active else c["text_sec"])
        self.screen.blit(img, img.get_rect(center=rect.center))
        self.hit.append((rect, action))

    # -- input
    def on_key(self, ev):
        mods = pygame.key.get_mods()
        ctrl, shift = mods & pygame.KMOD_CTRL, mods & pygame.KMOD_SHIFT
        if self.editing:
            key, t = self.editing
            if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.commit_edit()
            elif ev.key == pygame.K_ESCAPE:
                self.editing = None
            elif ev.key == pygame.K_BACKSPACE:
                self.editing = (key, t[:-1])
            elif ctrl and ev.key == pygame.K_v:
                try:
                    pygame.scrap.init()
                    clip = pygame.scrap.get(pygame.SCRAP_TEXT)
                    if clip:
                        self.editing = (key, t + clip.decode("utf-8", "ignore").rstrip("\x00"))
                except Exception:
                    pass
            return True
        rows = self.rows()
        if ctrl and ev.key == pygame.K_s:
            self.save()
        elif ctrl and ev.key == pygame.K_z:
            self.revert()
        elif ev.key == pygame.K_UP:
            self.sel = (self.sel - 1) % max(1, len(rows))
        elif ev.key == pygame.K_DOWN:
            self.sel = (self.sel + 1) % max(1, len(rows))
        elif ev.key == pygame.K_PAGEUP:
            self.sel = max(0, self.sel - 8)
        elif ev.key == pygame.K_PAGEDOWN:
            self.sel = min(len(rows) - 1, self.sel + 8)
        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE) and rows:
            self.activate(rows[self.sel])
        elif ev.key in (pygame.K_LEFT, pygame.K_RIGHT) and rows:
            self.change(rows[self.sel], -1 if ev.key == pygame.K_LEFT else 1, bool(shift))
        elif ev.key == pygame.K_TAB and len(self.files) > 1:
            self.fi, self.path, self.sel = (self.fi + 1) % len(self.files), [], 0
        elif ev.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
            if not self.back():
                return self.try_quit()
        return True

    def on_click(self, pos, button):
        if button in (4, 5):
            return True
        for rect, action in reversed(self.hit):
            if not rect.collidepoint(pos):
                continue
            kind = action[0]
            if kind == "select":
                rows = self.rows()
                if self.sel == action[1] and rows:
                    self.activate(rows[action[1]])
                self.sel = action[1]
            elif kind == "toggle":
                self.change(action[1], 1)
            elif kind == "change":
                self.change(action[1], action[2], bool(pygame.key.get_mods() & pygame.KMOD_SHIFT))
            elif kind == "file":
                self.fi, self.path, self.sel = action[1], [], 0
            elif kind == "back":
                if not self.back():
                    return self.try_quit()
            elif kind == "save":
                self.save()
            elif kind == "revert":
                self.revert()
            return True
        if self.editing:
            self.commit_edit()
        return True

    def try_quit(self):
        """Quit, unless there are unsaved changes: then the first try only warns, and
        a second one within 3 s quits anyway. Returns True to keep running."""
        now = pygame.time.get_ticks()
        if any(f.dirty for f in self.files) and now > self._quit_deadline:
            self.say("Unsaved changes - Ctrl+S to save, or quit again to throw them away.")
            self._quit_deadline = now + 3000
            return True
        return False

    def run(self):
        clock = pygame.time.Clock()
        running = True
        while running:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    running = self.try_quit()
                elif ev.type == pygame.KEYDOWN:
                    running = self.on_key(ev)
                elif ev.type == pygame.TEXTINPUT and self.editing:
                    self.editing = (self.editing[0], self.editing[1] + ev.text)
                elif ev.type == pygame.MOUSEBUTTONDOWN:
                    running = self.on_click(ev.pos, ev.button)
                elif ev.type == pygame.MOUSEWHEEL:
                    self.sel = max(0, min(len(self.rows()) - 1, self.sel - ev.y))
            self.draw()
            clock.tick(FPS)
        pygame.quit()


def main():
    paths = sys.argv[1:] or [p for p in (os.path.join(HERE, "config.json"), os.path.join(HERE, "settings.json"))
                             if os.path.exists(p) and os.path.getsize(p) > 2]
    files = []
    for p in paths:
        try:
            files.append(ConfigFile(p))
        except (OSError, ValueError) as e:
            print(f"Can't read {p}: {e}")
    if not files:
        print("No config.json here to edit.")
        return 1
    Options(files).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
