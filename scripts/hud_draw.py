# hud_draw.py — HUD and panel rendering helpers for KIDA
#
# Everything in this module is pure drawing — no hardware calls,
# no state mutations.  Pass in what you need, get pixels out.

import pygame
import state
import mode_manager
import camera_actions
from state import DriveMode

# ── Mode label config ──
_MODE_LABEL = {
    DriveMode.KEYBOARD:      ("KB",   (100, 220, 140)),
    DriveMode.IR_REMOTE:     ("IR",   (100, 180, 255)),
    DriveMode.AUTONOMOUS:    ("AUTO", (255, 190,  80)),
    DriveMode.LINE_FOLLOWER: ("LF",   (200, 100, 255)),
    DriveMode.WATCHDOG:      ("WATCH",(255,  80,  80)),
    DriveMode.LANE_DETECT:   ("LANE", ( 80, 208, 255)),
    DriveMode.PERSON_FOLLOW: ("FOLLOW",(120, 255, 200)),
    DriveMode.IDLE:          ("IDLE", (180,  80,  80)),
}

# ── Panel surface cache (avoids per-frame allocation) ──
_panel_cache: dict = {}


def draw_panel(surface: pygame.Surface, rect: pygame.Rect,
               fill=(14, 18, 30), alpha=210,
               border=(50, 70, 110), radius=6) -> None:
    key = (rect.size, fill, alpha, border, radius)
    if key not in _panel_cache:
        s = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(s, (*fill, alpha), s.get_rect(), border_radius=radius)
        pygame.draw.rect(s, (*border, 255), s.get_rect(), width=1, border_radius=radius)
        _panel_cache[key] = s
    surface.blit(_panel_cache[key], rect.topleft)


def draw_camera_panel(surface: pygame.Surface, frame, rect: pygame.Rect,
                      label: str, label_font, nosig_font) -> None:
    if frame is not None:
        try:
            surf = pygame.surfarray.make_surface(frame.swapaxes(0, 1))
            surf = pygame.transform.scale(surf, rect.size)
            surface.blit(surf, rect.topleft)
        except Exception as e:
            print(f"[Draw {label}] {e}")
    else:
        draw_panel(surface, rect, fill=(8, 10, 18), alpha=240)
        sig = nosig_font.render(f"[ {label} — NO SIGNAL ]", True, (60, 75, 100))
        surface.blit(sig, sig.get_rect(center=rect.center))
    pygame.draw.rect(surface, (50, 72, 115), rect, 2)
    tag = label_font.render(label, True, (150, 185, 255))
    surface.blit(tag, (rect.x + 6, rect.y + 5))


def draw_static_panel(surface: pygame.Surface, image_surf, rect: pygame.Rect,
                      label: str, label_font, nosig_font) -> None:
    """Like draw_camera_panel but for a pre-built, pre-scaled static Surface
    (the last-photo panel, the character face) instead of a live frame."""
    if image_surf is not None:
        surface.blit(image_surf, rect.topleft)
    else:
        draw_panel(surface, rect, fill=(8, 10, 18), alpha=240)
        sig = nosig_font.render(f"[ {label} — NO SIGNAL ]", True, (60, 75, 100))
        surface.blit(sig, sig.get_rect(center=rect.center))
    pygame.draw.rect(surface, (50, 72, 115), rect, 2)
    tag = label_font.render(label, True, (150, 185, 255))
    surface.blit(tag, (rect.x + 6, rect.y + 5))


def draw_status_strip(surface: pygame.Surface, fonts: dict,
                      hud_y: int, sen_x1: int,
                      motor_speed: int, cpu_temp,
                      cpu: float, ram: float, local_ip: str,
                      inference_on: bool,
                      bus_v: float, cur_ma: float,
                      pwr_w: float, bat_pct: float,
                      music_on: bool = False) -> None:
    """Power row + status row + hint row."""
    cur_mode              = mode_manager.current_mode()
    mode_label, mode_color = _MODE_LABEL.get(cur_mode, ("???", (200, 200, 200)))
    music_sym             = "▶" if music_on else "■"

    pw = fonts["sm"].render(
        f"  ⚡{bus_v:.2f}V  {cur_ma/1000:.3f}A  {pwr_w:.2f}W  🔋{bat_pct:.0f}%",
        True, (70, 215, 100),
    )
    surface.blit(pw, (sen_x1, hud_y + 6))

    st_base = fonts["sm"].render(
        f"  Spd:{motor_speed}  T:{cpu_temp}  CPU:{cpu:.0f}%  "
        f"RAM:{ram:.0f}%  IP:{local_ip}  "
        f"Inf:{'ON' if inference_on else 'off'}  Mus:{music_sym}  Mode:",
        True, (160, 190, 235),
    )
    surface.blit(st_base, (sen_x1, hud_y + 24))

    mode_surf = fonts["sm"].render(f" [{mode_label}]", True, mode_color)
    surface.blit(mode_surf, (sen_x1 + st_base.get_width(), hud_y + 24))

    hint = fonts["xs"].render(
        "  1=KB  2=IR  3=AUTO  4=IDLE  5=LINE  6=WATCH  7=LANE  8=FOLLOW",
        True, (80, 100, 140),
    )
    surface.blit(hint, (sen_x1, hud_y + 42))

    # Gamepad plugged into *this* machine (joystick_drive.py sets the name)
    pad = getattr(state, "joystick_name", None)
    pending = getattr(state, "joystick_pending_mode", None)
    pad_text = f"  🎮 {pad[:28]}" if pad else "  🎮 no pad"
    if pad and pending:
        pad_text += f"  → mode {pending}…"
    pad_surf = fonts["xs"].render(
        pad_text, True, (100, 220, 140) if pad else (90, 90, 110),
    )
    surface.blit(pad_surf, (sen_x1 + hint.get_width() + 12, hud_y + 42))

    # Her inner life (kida_mind_host.py keeps this current); absent = no mind running
    mind = getattr(state, "mind_label", None)
    if mind:
        mind_surf = fonts["xs"].render(f"  ♡ {mind}", True, (200, 160, 235))
        surface.blit(mind_surf, (sen_x1 + hint.get_width() + 12 + pad_surf.get_width() + 8, hud_y + 42))


def draw_sensor_grid(surface: pygame.Surface, fonts: dict,
                     sensor_rows: list, lbl_surfaces: list,
                     sen_x1: int, sen_x2: int, sen_top: int) -> None:
    mid = (len(sensor_rows) + 1) // 2
    for i, ((attr, _), lbl_surf) in enumerate(zip(sensor_rows, lbl_surfaces)):
        col = 0 if i < mid else 1
        row = i if i < mid else i - mid
        x   = sen_x1 + col * (sen_x2 - sen_x1)
        y   = sen_top + row * 19
        surface.blit(lbl_surf, (x, y))
        val_s = fonts["xs"].render(
            str(getattr(state, attr, "—")), True, (215, 230, 255)
        )
        surface.blit(val_s, (x + 88, y))


def draw_button_panel(surface: pygame.Surface, fonts: dict,
                      buttons: list, hud_y: int,
                      btn_panel_x: int, btn_panel_rect: pygame.Rect,
                      music_on: bool = False) -> None:
    draw_panel(surface, btn_panel_rect, fill=(10, 14, 26), alpha=230,
               border=(42, 62, 100), radius=6)
    surface.blit(
        fonts["hd"].render("CONTROLS", True, (100, 150, 210)),
        (btn_panel_x, hud_y + 8),
    )
    btn_cols   = 2
    btn_margin = 6
    bx0        = btn_panel_x + 4
    by0        = hud_y + 34
    btn_w      = (btn_panel_rect.width - btn_margin * (btn_cols + 1)) // btn_cols

    for idx, button in enumerate(buttons):
        col = idx % btn_cols
        row = idx // btn_cols
        button.rect.x     = bx0 + col * (btn_w + btn_margin)
        button.rect.y     = by0 + row * (button.rect.height + btn_margin)
        button.rect.width = btn_w
        if hasattr(button, "label") and button.label in ("Play", "▶", "Play Music"):
            button.enabled = not music_on
        if hasattr(button, "label") and button.label.startswith("Cam:"):
            button.text = button.label = f"Cam: {camera_actions.active_cam_id}"
        if hasattr(button, "label") and button.label in ("LOCKED", "Lock Motors"):
            button.text = button.label = "LOCKED" if state.motor_lock else "Lock Motors"
            button.base_color = (200, 60, 60) if state.motor_lock else (140, 200, 140)
        if hasattr(button, "label") and button.label.startswith("Scheme:"):
            button.text = button.label = f"Scheme: {state.drive_scheme}"
        button.draw(surface)


def draw_idle_overlay(surface: pygame.Surface, fonts: dict) -> None:
    overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 220))
    surface.blit(overlay, (0, 0))
    msg = fonts["hd"].render(
        "[ IDLE — press 1-7 to select a mode ]",
        True, (140, 60, 60),
    )
    surface.blit(msg, msg.get_rect(
        center=(surface.get_width() // 2, surface.get_height() // 2)
    ))


# ── Mind panel (kida_mind) ────────────────────────────────────────────────
# Shared by the Pi HUD (ui.py fills `mind` from kida_mind_host) and the PC
# controller (filled from the robot's /mind). `mind` is Mind.status() plus
# "person" and "last_exchange"; None/{} = no mind running (panel not drawn).
_MIND_BARS = (("Lonely", "social"), ("Curious", "curiosity"), ("Jumpy", "security"), ("Sleepy", "sleepiness"))


def _wrap(font, text: str, width: int, max_lines: int) -> list:
    words, lines, line = (text or "").split(), [], ""
    for w in words:
        trial = f"{line} {w}".strip()
        if font.size(trial)[0] <= width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = w
        if len(lines) >= max_lines:
            break
    if line and len(lines) < max_lines:
        lines.append(line)
    if len(lines) == max_lines and " ".join(lines) != " ".join(words):
        lines[-1] = lines[-1].rstrip(".,") + "…"
    return lines


def mind_panel_rect(sw: int, sh: int, hud_y: int, sen_x2: int, btn_panel_x: int):
    """Where the mind panel goes: the free HUD space between the sensor grid
    and the button panel. None if the window is too narrow for it."""
    x = sen_x2 + 260
    w = btn_panel_x - 18 - x
    if w < 260:
        return None
    return pygame.Rect(x, hud_y + 62, w, sh - hud_y - 70)


def draw_mind_panel(surface: pygame.Surface, fonts: dict, rect, mind: dict | None) -> None:
    if rect is None or not mind or not mind.get("mood"):
        return
    draw_panel(surface, rect, fill=(12, 10, 24), alpha=225, border=(70, 52, 110), radius=6)
    x, y, w = rect.x + 10, rect.y + 8, rect.width - 20
    label = mind["mood"].get("label", "?") + ("  (asleep)" if mind.get("sleeping") else "")
    head = fonts["sm"].render(f"MIND  ♡ {label}", True, (205, 170, 240))
    surface.blit(head, (x, y))
    if mind.get("person"):
        who = fonts["xs"].render(f"with {mind['person']}", True, (120, 230, 170))
        surface.blit(who, (x + head.get_width() + 14, y + 3))
    y += 24

    drives = mind.get("drives", {})
    bar_w = max(60, (w - 4 * 64) // 4)
    for i, (name, key) in enumerate(_MIND_BARS):
        bx = x + i * (bar_w + 64)
        surface.blit(fonts["xs"].render(name, True, (150, 140, 185)), (bx, y))
        track = pygame.Rect(bx + 58, y + 4, bar_w, 8)
        pygame.draw.rect(surface, (30, 28, 50), track, border_radius=3)
        v = max(0.0, min(1.0, float(drives.get(key, 0) or 0)))
        if v:
            pygame.draw.rect(surface, (150, 120, 240), (track.x, track.y, int(track.w * v), track.h), border_radius=3)
    y += 22

    bottom = rect.bottom - 6
    thought = mind.get("thought")
    if thought and y + 16 < bottom:
        for line in _wrap(fonts["xs"], "… " + thought, w, 2):
            surface.blit(fonts["xs"].render(line, True, (190, 180, 220)), (x, y))
            y += 16
        y += 4
    ex = mind.get("last_exchange") or {}
    for who, key, color in (("You", "you", (140, 170, 220)), ("KIDA", "kida", (230, 190, 240))):
        if ex.get(key) and y + 16 < bottom:
            for line in _wrap(fonts["xs"], f"{who}: {ex[key]}", w, 2):
                if y + 16 >= bottom:
                    break
                surface.blit(fonts["xs"].render(line, True, color), (x, y))
                y += 16
