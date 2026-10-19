# keymap.py — every key, gamepad button and IR remote button KIDA-01 takes, in one place
#
# Pads drive in KEYBOARD mode; their buttons work in any mode.
#
# Read by the PC controller's keys window (F1; H is "go home" here) and by the
# README's Controls section:
#
#     python controller/scripts/keymap.py        prints the README tables
#
# The data is plain Python (no pygame at import), so the robot can use the same
# file: copied to scripts/keymap.py on the Pi it can feed her own HUD's keys
# window and a /keymap route for the web dashboard, so none of them drift apart.

ROBOT = "KIDA-01"

# (section, [(keys, what it does), ...])
KEYBOARD = [
    ("Modes (any time)", [
        ("1", "KEYBOARD: you drive"),
        ("2", "IR REMOTE: the IR remote drives"),
        ("3", "AUTONOMOUS: obstacle avoidance"),
        ("4", "IDLE: asleep, motors off"),
        ("5", "LINE FOLLOWER"),
        ("6", "WATCHDOG: person alarm"),
        ("7", "LANE DETECT (Hailo)"),
        ("8", "PERSON FOLLOW (cam 1)"),
    ]),
    ("Drive (KEYBOARD mode)", [
        ("W A S D", "WASD scheme: forward, left, back, right; W+A etc. curve"),
        ("Q A / W S", "QAWS scheme: left track / right track, forward and back"),
        ("< or ,", "WASD scheme"),
        ("> or .", "QAWS (tank) scheme"),
        ("X", "next speed"),
        ("SPACE", "hard stop: motors and music"),
    ]),
    ("Camera, lights, music", [
        ("C", "photo"),
        ("V", "video"),
        ("I", "cam 0 inference (YOLO) on / off"),
        ("L", "lights on / off"),
        ("K", "light effects on / off"),
        ("M", "play music (skip when playing)"),
    ]),
    ("Robot", [
        ("U", "lock the motors / unlock (asks for the password)"),
        ("T", "type a message to her (PC controller)"),
        ("H", "go home (PC controller)"),
        ("F1", "this keys window (PC controller)"),
        ("ESC", "close the window (on her: the UI restarts)"),
        ("Q", "quit (WASD scheme; on her: stops for good)"),
    ]),
]

GAMEPAD = [
    ("Gamepad (on her or the PC)", [
        ("Left stick", "drive (WASD scheme)"),
        ("LT / RT", "left / right track, analog (QAWS scheme)"),
        ("LB / RB", "QAWS: that track backwards; WASD: previous / next mode"),
        ("Right stick", "aim the ultrasonic / laser servo"),
        ("A", "photo"),
        ("B", "stop"),
        ("X / Y", "speed down / up"),
        ("D-pad ← / →", "previous / next mode (set once you stop pressing)"),
        ("D-pad ↑", "video on / off (RT too, in the WASD scheme)"),
        ("Start", "lock the motors / unlock prompt"),
        ("Back", "LIDAR sweep"),
    ]),
    ("ARM's joystick (raw sticks)", [
        ("Stick", "drive"),
        ("Hat ← / →", "previous / next mode"),
        ("Hat ↑", "video on / off"),
        ("Trigger", "photo (as A)"),
        ("Button 1", "stop (as B)"),
        ("Button 2 / 3", "speed down / up (as X / Y)"),
    ]),
]

IR_REMOTE = [
    ("IR remote", [
        ("1", "IR REMOTE mode"),
        ("2", "KEYBOARD mode"),
        ("3", "AUTONOMOUS"),
        ("4", "IDLE"),
        ("5", "LINE FOLLOWER"),
        ("6", "WATCHDOG"),
        ("↑ ↓ ← →", "drive (IR REMOTE mode); let go to stop"),
        ("Stop", "stop"),
        ("Play", "play music (skip when playing)"),
        ("Fast forward / Blue", "speed up"),
        ("Yellow", "speed down"),
        ("Skip", "switch between IR REMOTE and KEYBOARD"),
        ("Red / Green", "lock / unlock the motors (no password)"),
    ]),
]


def sections() -> list:
    return KEYBOARD + GAMEPAD + IR_REMOTE


def as_dict() -> dict:
    """For a /keymap route on the robot (a web dashboard keys panel)."""
    def conv(groups):
        return [{"title": t, "keys": [{"keys": k, "does": d} for k, d in rows]} for t, rows in groups]
    return {"robot": ROBOT, "keyboard": conv(KEYBOARD), "gamepad": conv(GAMEPAD), "ir": conv(IR_REMOTE)}


def markdown() -> str:
    """The README's Controls tables."""
    out = []
    for title, rows in sections():
        out += [f"**{title}**", "", "| Key | Does |", "| :--- | :--- |"]
        out += [f"| <kbd>{k}</kbd> | {d} |" for k, d in rows]
        out.append("")
    return "\n".join(out)


def draw(screen, title=None) -> None:
    """The keys window over whatever is on screen: sections in columns, close with F1 or ESC."""
    import pygame
    W, H = screen.get_size()
    head = pygame.font.SysFont("Courier New", 20, bold=True)
    shade = pygame.Surface((W, H), pygame.SRCALPHA)
    shade.fill((0, 0, 0, 205))
    screen.blit(shade, (0, 0))
    panel = pygame.Rect(30, 30, W - 60, H - 60)
    pygame.draw.rect(screen, (10, 16, 28), panel, border_radius=12)
    pygame.draw.rect(screen, (80, 160, 255), panel, width=1, border_radius=12)
    screen.blit(head.render(title or f"{ROBOT} KEYS", True, (80, 160, 255)), (panel.x + 24, panel.y + 16))
    groups = sections()
    top, bottom = panel.y + 60, panel.bottom - 16

    def wrap(font, text, width):
        lines, line = [], ""
        for word in text.split():
            trial = f"{line} {word}".strip()
            if line and font.size(trial)[0] > width:
                lines.append(line)
                line = word
            else:
                line = trial
        return lines + [line] if line else lines

    def layout(size, ncols):
        """Where each section goes, or None if they don't all fit."""
        keyf = pygame.font.SysFont("Courier New", size, bold=True)
        desc = pygame.font.SysFont("Arial", size)
        col_w = (panel.width - 48 - 24 * (ncols - 1)) // ncols
        row_h = desc.get_linesize()
        place, col, y = [], 0, top
        for _, rows in groups:
            key_w = max(keyf.size(k)[0] for k, _ in rows) + 16      # this section's longest key
            h = row_h + 8 + sum(len(wrap(desc, d, col_w - key_w - 9)) * row_h + 2 for _, d in rows) + 12
            if y + h > bottom and y > top:
                col, y = col + 1, top
            if col >= ncols or y + h > bottom:
                return None
            place.append((col, y, key_w))
            y += h
        return keyf, desc, col_w, row_h, place

    # Biggest text that fits, in 2 or 3 columns (3 only when there's room for them)
    fit = None
    for size in (15, 14, 13, 12, 11):
        for ncols in ((2, 3) if panel.width >= 1000 else (2,)):
            fit = layout(size, ncols)
            if fit:
                break
        if fit:
            break
    if not fit:
        fit = layout(11, 3) or layout(11, 2) or (None,) * 5
    keyf, desc, col_w, row_h, place = fit
    if place is None:
        return
    hint = desc.render("F1 or ESC closes", True, (120, 130, 150))
    screen.blit(hint, (panel.right - 24 - hint.get_width(), panel.y + 20))

    for (title_s, rows), (col, y, key_w) in zip(groups, place):
        x = panel.x + 24 + col * (col_w + 24)
        pygame.draw.rect(screen, (80, 160, 255), pygame.Rect(x, y + 3, 3, 12))
        screen.blit(keyf.render(title_s.upper(), True, (140, 150, 170)), (x + 9, y))
        y += row_h + 8
        for keys, does in rows:
            screen.blit(keyf.render(keys, True, (255, 180, 60)), (x + 9, y))
            for line in wrap(desc, does, col_w - key_w - 9):
                screen.blit(desc.render(line, True, (225, 230, 240)), (x + key_w, y))
                y += row_h
            y += 2

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")      # the arrows, on a Windows console too
    print(markdown())
