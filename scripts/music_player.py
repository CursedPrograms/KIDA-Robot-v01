#!/usr/bin/env python3
# music_player.py
# Drop-in replacement for music.py — delete music.py after switching over.

import os
import re
import glob
import random
import logging
import pygame
import config
import leds

logger = logging.getLogger(__name__)


class MusicPlayer:
    """
    Pygame-backed music player with shuffle, skip, and auto-advance.
    Replaces the procedural music.py module.

    Usage
    -----
    player = MusicPlayer()        # reads config.MUSIC_FOLDER automatically
    player.start()                # play from track 0
    player.skip()                 # skip to next track
    player.stop()                 # stop + kill LEDs
    player.handle_event(event)    # call inside pygame event loop

    Attributes
    ----------
    current_track : str
        Basename of the currently loaded track, or empty string if none.
    playing : bool
        True while a track is actively playing.
    """

    # One shared event ID so the rest of the codebase can check against it
    SONG_END = pygame.USEREVENT + 1

    def __init__(self, folder: str = None, shuffle: bool = False):
        pygame.mixer.init()
        pygame.mixer.music.set_endevent(self.SONG_END)

        self.current_track: str  = ""
        self.current_path:  str  = ""     # the full path (the visualizer reads the file)
        self._loaded:       str  = ""     # loaded by load_number(), waiting for start_loaded()
        self.playing:       bool = False
        self.paused:        bool = False
        self._enabled:      bool = True   # mirrors music.py's music_enabled flag
        self._manual_stop:  bool = False
        self._index:        int  = 0

        folder = folder or config.MUSIC_FOLDER
        self._playlist = self._load_playlist(folder)

        logger.info(
            "MusicPlayer loaded %d tracks from %s", len(self._playlist), folder
        )
        print(f"🎵 Music system initialized. {len(self._playlist)} tracks loaded.")

    # ─────────────────────────────────────────────
    #  Private helpers
    # ─────────────────────────────────────────────

    def _load_playlist(self, folder: str) -> list[str]:
        """Collect all supported tracks from folder (uses config.SUPPORTED_FORMATS)."""
        tracks = [
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if f.lower().endswith(config.SUPPORTED_FORMATS)
        ]
        tracks.sort()
        return tracks

    def _play_index(self, index: int) -> None:
        """Internal: load and play track at playlist[index], with LED kick."""
        if not self._playlist:
            logger.warning("Playlist is empty — nothing to play")
            return

        self._index        = index % len(self._playlist)
        path               = self._playlist[self._index]
        self._manual_stop  = False

        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            self.current_track = os.path.basename(path)
            self.current_path  = path
            self.playing       = True
            self.paused        = False
            leds.start_music_wave()
            logger.info("Now playing: %s", self.current_track)
            print(f"▶️  Playing: {path}")
        except pygame.error as e:
            logger.error("Failed to play %s: %s", path, e)

    # ─────────────────────────────────────────────
    #  Public API  (mirrors music.py functions)
    # ─────────────────────────────────────────────

    def start(self) -> None:
        """Reset to track 0 and begin playback (mirrors music.start_music)."""
        if not self._playlist:
            print("⚠️  No tracks to play.")
            return
        self._enabled = True
        self._play_index(0)

    def stop(self) -> None:
        """Stop playback and LEDs (mirrors music.stop_music)."""
        self._enabled     = False
        self._manual_stop = True
        pygame.mixer.music.stop()
        leds.stop_music_wave()
        self.playing       = False
        self.paused        = False
        self.current_track = ""
        self.current_path  = ""
        print("⏹️  Music stopped.")

    def skip(self) -> None:
        """Skip current track and play the next one (mirrors music.skip_music)."""
        if not self._playlist:
            print("⚠️  No tracks to skip.")
            return
        pygame.mixer.music.stop()
        leds.stop_music_wave()
        self._enabled = True
        self._advance()

    def play_next(self) -> None:
        """Advance to next track; respects the enabled flag (auto-advance path)."""
        if not self._enabled:
            return
        self._advance()

    # Alias kept for any code still calling the old name
    safe_play_next = play_next

    def pause(self) -> None:
        """Pause playback."""
        if self.playing and not self.paused:
            pygame.mixer.music.pause()
            self.paused  = True
            self.playing = False

    def resume(self) -> None:
        """Resume paused playback."""
        if self.paused:
            pygame.mixer.music.unpause()
            self.paused  = False
            self.playing = True

    def handle_event(self, event: pygame.event.Event) -> None:
        """
        Pass every pygame event here to handle track auto-advance.
        Replaces music.handle_music_event(event).
        """
        if event.type != self.SONG_END:
            return
        if self._manual_stop:
            self._manual_stop = False
            return
        logger.debug("Track ended — advancing")
        self.play_next()

    def is_playing(self) -> bool:
        """Return True if music is currently playing (mirrors music.is_music_playing)."""
        return pygame.mixer.music.get_busy()

    # ─────────────────────────────────────────────
    #  RIFT's music together (fleet_music.py) and the visualizer (music_viz.py)
    # ─────────────────────────────────────────────

    def load_number(self, n: int) -> bool:
        """Load the track whose file name holds the number n (track07.mp3 is 7, as on NORA's SD
        card), so start_loaded() can start it on the beat. False if there's no such track."""
        for i, path in enumerate(self._playlist):
            m = re.search(r"(\d+)", os.path.basename(path))
            if m and int(m.group(1)) == n:
                try:
                    pygame.mixer.music.load(path)
                except pygame.error as e:
                    logger.error("Failed to load %s: %s", path, e)
                    return False
                self._index, self._loaded = i, path
                self._manual_stop = True      # loading stopped whatever was playing: no auto-advance
                return True
        return False

    def start_loaded(self) -> None:
        """Start the track load_number() loaded, now."""
        if not self._loaded:
            return
        self._manual_stop = False
        self._enabled     = True
        pygame.mixer.music.play()
        self.current_track = os.path.basename(self._loaded)
        self.current_path  = self._loaded
        self.playing, self.paused, self._loaded = True, False, ""
        leds.start_music_wave()
        logger.info("Now playing (with the fleet): %s", self.current_track)

    def position_s(self) -> float:
        """Seconds into the current track."""
        return max(0, pygame.mixer.music.get_pos()) / 1000.0

    # ─────────────────────────────────────────────
    #  Internal
    # ─────────────────────────────────────────────

    def _advance(self) -> None:
        next_index = (self._index + 1) % len(self._playlist)
        self._play_index(next_index)

    # ─────────────────────────────────────────────
    #  Info
    # ─────────────────────────────────────────────

    @property
    def track_count(self) -> int:
        return len(self._playlist)

    def __repr__(self) -> str:
        return (
            f"MusicPlayer(tracks={self.track_count}, "
            f"playing={self.playing}, current='{self.current_track}')"
        )