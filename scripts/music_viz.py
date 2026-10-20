#!/usr/bin/env python3
"""
music_viz.py — the music visualizer's bars, from the song itself (KIDA-00's, for KIDA-01).

    bars = MusicBars()
    ...every frame:  amps = bars.amplitudes(music_ctrl)   # 22 levels 0..1, or None
                     hud_draw.draw_music_bars(screen, rect, amps)

When a track starts, audio_analysis.AudioAnalyzer reads it on a worker thread (a few
seconds for a song); until then, or if pydub / ffmpeg are missing, amplitudes() gives
None and the bars just animate.
"""

import logging
import threading

logger = logging.getLogger("kida.music_viz")

try:
    from audio_analysis import AudioAnalyzer
    _audio_error = None
except Exception as _e:               # pydub / ffmpeg missing: the bars animate instead
    AudioAnalyzer = None
    _audio_error = _e                 # `_e` itself is gone once this block ends

BARS = 22


class MusicBars:
    def __init__(self, bars: int = BARS):
        self.bars = bars
        self._path = None
        self._analyzer = None
        if AudioAnalyzer is None:
            logger.warning("audio_analysis unavailable (%s): the music bars animate, not measured", _audio_error)

    def _load(self, path: str) -> None:
        try:
            analyzer = AudioAnalyzer(path, num_bars=self.bars)
        except Exception as e:
            logger.warning("Can't read %s for the bars: %s", path, e)
            return
        if path == self._path:        # still the same song
            self._analyzer = analyzer

    def amplitudes(self, player):
        """The bars for where the song is now, or None (nothing playing, or not read yet)."""
        if player is None or not player.playing:
            return None
        path = getattr(player, "current_path", "")
        if path != self._path:        # a new song: read it in the background
            self._path, self._analyzer = path, None
            if path and AudioAnalyzer is not None:
                threading.Thread(target=self._load, args=(path,), daemon=True, name="music-bars").start()
            return None
        if self._analyzer is None:
            return None
        try:
            return self._analyzer.get_amplitudes(player.position_s())
        except Exception:
            return None
