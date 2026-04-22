# buttons.py — UI button widget and button definitions for KIDA

import pygame
from leds import toggle_leds
from camera_actions import take_photo, start_video, stop_video
from music import play_next_track, stop_music, skip_music
from arduino import send_command
from mode_control import switch_mode


class Button:
    def __init__(self, rect, color, text, action):
        self.rect         = pygame.Rect(rect)
        self.base_color   = color
        self.hover_color  = tuple(min(c + 30, 255) for c in color)
        self.pressed_color = tuple(max(c - 30, 0) for c in color)
        self.text         = text
        self.label        = text   # alias used by hud_draw.py
        self.action       = action
        self.font         = pygame.font.SysFont(None, 20)
        self.enabled      = True   # False = greyed out, click ignored
        self.is_hovered   = False
        self.is_pressed   = False

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
        label = self.font.render(self.text, True, text_color)
        surface.blit(label, label.get_rect(center=self.rect.center))

    def update(self, mouse_pos, mouse_down):
        self.is_hovered = self.rect.collidepoint(mouse_pos)
        self.is_pressed = self.is_hovered and mouse_down

    def is_clicked(self, pos) -> bool:
        return self.enabled and self.rect.collidepoint(pos)


def create_buttons() -> list:
    pink = (255, 182, 193)

    return [
        Button((650,  20, 160, 40), pink, "Take Photo",      take_photo),
        Button((650,  70, 160, 40), pink, "Record Video",    start_video),
        Button((650, 120, 160, 40), pink, "Keyboard Mode",   lambda: switch_mode(1)),
        Button((650, 170, 160, 40), pink, "Autonomous Mode", lambda: switch_mode(3)),
        Button((650, 220, 160, 40), pink, "Play Music",      play_next_track),
        Button((650, 270, 160, 40), pink, "Next Track",      skip_music),
        Button((650, 320, 160, 40), pink, "Stop Music",      stop_music),
        Button((650, 370, 160, 40), pink, "Toggle LEDs",     toggle_leds),
    ]
