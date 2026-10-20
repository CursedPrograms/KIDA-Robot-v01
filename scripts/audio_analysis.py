#!/usr/bin/env python3

import logging
import numpy as np
from pydub import AudioSegment

logger = logging.getLogger(__name__)


class AudioAnalyzer:
    """
    Pre-computes per-bar RMS amplitude data from an audio file so the
    waveform visualiser can query it cheaply at playback time.
    """

    def __init__(self, filepath: str, num_bars: int = 50, window_s: float = 0.5):
        self.num_bars = num_bars

        audio = AudioSegment.from_file(filepath)
        samples = np.array(audio.get_array_of_samples(), dtype=np.float32)

        # Mix stereo down to mono
        if audio.channels == 2:
            samples = samples.reshape(-1, 2).mean(axis=1)

        self.sample_rate: int   = audio.frame_rate
        self.duration:    float = len(audio) / 1000.0  # seconds

        # Normalise to [-1, 1]
        peak = np.max(np.abs(samples))
        if peak > 0:
            samples /= peak
        self._samples = samples

        # Each bar covers window_s / num_bars of audio, so the bars show the
        # half-second around the playhead (not the whole song squeezed in)
        self._chunk = max(1, int(self.sample_rate * window_s / num_bars))

        logger.info(
            "AudioAnalyzer: %s | %.1fs | %d Hz | %d bars",
            filepath, self.duration, self.sample_rate, num_bars,
        )

    # ── Public API ────────────────────────────────────────────

    def get_amplitudes(self, current_time: float) -> list[float]:
        """
        Return a list of `num_bars` RMS amplitudes (0.0–1.0) for the window
        starting at `current_time`, clamped to the ends of the file.
        """
        needed = self._chunk * self.num_bars
        start  = int(current_time * self.sample_rate)
        start  = max(0, min(start, len(self._samples) - needed))

        amps = []
        for i in range(self.num_bars):
            chunk = self._samples[start + i * self._chunk : start + (i + 1) * self._chunk]
            rms   = float(np.sqrt(np.mean(chunk ** 2))) if len(chunk) else 0.0
            # Music RMS of a peak-normalised track sits around 0.1–0.4; scale
            # it up so the bars use the full height
            amps.append(min(rms * 2.5, 1.0))

        return amps
