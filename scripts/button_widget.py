# button_widget.py — pure pygame Button widget for KIDA
#
# No hardware calls, no network calls — just a clickable rect. Shared by
# scripts/buttons.py (robot, wired to local hardware) and
# scripts/controller/buttons.py (remote controller, wired to /action POSTs)
# so the two button panels always look and behave identically.

import pygame


class Button:
    def __init__(self, rect, color, text, action):
        self.rect          = pygame.Rect(rect)
        self.base_color    = color
        self.hover_color   = tuple(min(c + 30, 255) for c in color)
        self.pressed_color = tuple(max(c - 30,   0) for c in color)
        self.text          = text
        self.label         = text   # alias used by hud_draw.py
        self.action        = action
        self.font          = pygame.font.SysFont(None, 20)
        self.enabled       = True   # False = greyed out, click ignored
        self.is_hovered    = False
        self.is_pressed    = False

    def draw(self, surface):
        if not self.enabled:
            color = tuple(max(c - 60, 20) for c in self.base_color)
        elif self.is_pressed:
            color = self.pressed_color
        elif self.is_hovered:
            color = self.hover_color
        else:
            color = self.base_color

        pygame.draw.rect(surface, color, self.rect, border_radius=12)
        pygame.draw.rect(surface, (80, 80, 80), self.rect, 2, border_radius=12)

        text_color = (120, 120, 120) if not self.enabled else (0, 0, 0)
        text = self.text
        while len(text) > 1 and self.font.size(text)[0] > self.rect.width - 10:
            text = text[:-2] + "…"   # too long for the button: trim, never spill out
        label = self.font.render(text, True, text_color)
        surface.blit(label, label.get_rect(center=self.rect.center))

    def update(self, mouse_pos, mouse_down):
        self.is_hovered = self.rect.collidepoint(mouse_pos)
        self.is_pressed = self.is_hovered and mouse_down

    def is_clicked(self, pos) -> bool:
        return self.enabled and self.rect.collidepoint(pos)
