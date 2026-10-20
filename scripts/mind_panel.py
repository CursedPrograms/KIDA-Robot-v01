"""mind_panel.py - a robot's mind (mind.py's Mind) as a strip in a pygame controller window.

The same file in the controllers that use it (NORA, MILA, NIKA), like mind.py:

    mind_panel.draw(screen, pygame.Rect(10, H - 170, W - 20, 160), the_mind, f_med, f_sml,
                    "NORA", note="N: off", colours=(TEXT, DIM, WARN, ACCENT))

Her state, what she just said, and her thinking as it comes, newest at the bottom (the user loves
reading the robots' thoughts).
"""
import pygame


def wrap(text, font, width):
    lines = []
    for para in text.split("\n"):
        line = ""
        for word in para.split(" "):
            test = (line + " " + word).strip()
            if font.size(test)[0] <= width:
                line = test
            else:
                if line:
                    lines.append(line)
                line = word
        lines.append(line)
    return lines


def draw(screen, rect, mind, font, small, title, note="", colours=((225, 225, 230), (130, 130, 140), (220, 160, 80), (90, 200, 120))):
    text, dim, warn, accent = colours
    pygame.draw.rect(screen, (14, 16, 24), rect, border_radius=10)
    pygame.draw.rect(screen, accent if mind.on else dim, rect, width=2, border_radius=10)
    x, y, w = rect.x + 10, rect.y + 8, rect.width - 20
    head = f"{title} MIND: {mind.state}" + (f"   ({note})" if note else "")
    screen.blit(font.render(head, True, accent if mind.on else dim), (x, y))
    y += font.get_height() + 4
    if mind.said:
        for line in wrap(f'"{mind.said}"', font, w)[:2]:
            screen.blit(font.render(line, True, text), (x, y))
            y += font.get_height() + 2
    if mind.error:
        screen.blit(small.render(f"! {mind.error}"[:90], True, warn), (x, y))
        y += small.get_height() + 2
    thoughts = wrap(mind.thinking.strip(), small, w) if mind.thinking.strip() else []
    room = max(0, (rect.bottom - 6 - y) // (small.get_height() + 1))
    for line in thoughts[-room:] if room else []:
        screen.blit(small.render(line, True, dim), (x, y))
        y += small.get_height() + 1
