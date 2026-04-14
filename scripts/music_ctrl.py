# music_ctrl.py — thin wrappers around music.py that respect music_blocked

import pygame
import music

music_blocked = False


def hard_stop() -> None:
    global music_blocked
    music_blocked = True
    for fn in (pygame.mixer.music.stop, pygame.mixer.stop, music.stop_music):
        try:
            fn()
        except Exception:
            pass


def unblock() -> None:
    global music_blocked
    music_blocked = False


def safe_play_next() -> None:
    if not music_blocked:
        music.play_next_track()


def safe_skip() -> None:
    if not music_blocked:
        music.skip_music()


def toggle_or_skip() -> None:
    """M key behaviour: unblock then play/skip."""
    unblock()
    if not music.is_music_playing():
        music.play_next_track()
    else:
        safe_skip()


def handle_track_end_event(event) -> bool:
    """Returns True if the event was consumed."""
    if hasattr(music, "MUSIC_END_EVENT") and event.type == music.MUSIC_END_EVENT:
        if not music_blocked:
            music.play_next_track()
        return True
    return False
