"""
voice.py - listening to how you sound, and shaping how she sounds.

Listening: from a recording of what someone said, measure loudness, pitch (and
how much it moves), speaking rate, and the pauses. Those give cues - animated,
hurried, quiet, flat, hesitant - that colour how she reads the moment, on top
of the words. Prosody is a weak signal for emotion and this is deliberately
modest: it nudges her mood; it never decides anything alone.

Speaking: turn her mood and tiredness into Piper's prosody controls - speed,
variation, and the pause between sentences - so a sleepy KIDA drawls and a
happy one is quick and lively. A little chance is mixed in so no two
deliveries are identical.
"""

import random
import re
import wave

import numpy as np

FILLERS = re.compile(r"\b(um+|uh+|er+|erm|hmm+|uhm)\b|\b(i mean|you know|sort of|kind of)\b", re.I)


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, float(x)))


def read_wav(path):
    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1).astype(np.int16)
    return data, sr


def _f0(frame, sr, fmin=70, fmax=400):
    """Fundamental frequency of one frame by autocorrelation, or None if unvoiced."""
    frame = frame - frame.mean()
    n = len(frame)
    spec = np.fft.rfft(frame, 2 * n)
    r = np.fft.irfft(spec * np.conj(spec))[:n]
    if r[0] <= 1e-9:
        return None
    lo, hi = int(sr / fmax), min(int(sr / fmin), n - 1)
    if hi <= lo:
        return None
    lag = lo + int(np.argmax(r[lo:hi]))
    return sr / lag if r[lag] / r[0] > 0.3 else None


def analyze_samples(samples, sr):
    """Voice cues for a mono int16 clip, or None if there's too little speech."""
    x = np.asarray(samples, dtype=np.float32) / 32768.0
    frame, hop = int(0.04 * sr), int(0.02 * sr)
    if frame <= 0 or len(x) < frame * 5:
        return None
    n = 1 + (len(x) - frame) // hop
    rms = np.array([np.sqrt(np.mean(x[i * hop:i * hop + frame] ** 2)) for i in range(n)])
    floor = np.percentile(rms, 10)
    threshold = max(floor * 2.5, 0.01)
    speech = rms > threshold
    if speech.sum() < 5:
        return None

    first, last = int(np.argmax(speech)), n - 1 - int(np.argmax(speech[::-1]))
    span = speech[first:last + 1]
    speech_time = float(speech.sum() * hop / sr)

    # pauses: quiet stretches inside the utterance (not the lead-in or the tail)
    pauses, run = [], 0
    for s in span:
        if s:
            if run * hop / sr >= 0.25:
                pauses.append(run * hop / sr)
            run = 0
        else:
            run += 1
    total_span = len(span) * hop / sr
    pause_ratio = sum(pauses) / total_span if total_span else 0.0
    longest_pause = max(pauses) if pauses else 0.0

    # pitch
    pitches = []
    for i in np.flatnonzero(speech):
        f = _f0(x[i * hop:i * hop + frame], sr)
        if f:
            pitches.append(f)
    pitch_mean = float(np.mean(pitches)) if pitches else 0.0
    pitch_std_st = float(np.std(12 * np.log2(pitches))) if len(pitches) > 3 else 0.0   # semitones

    # speaking rate: energy peaks are syllable nuclei
    env = np.convolve(rms, np.ones(3) / 3, mode="same")
    peaks, last_peak = 0, -100
    for i in range(1, n - 1):
        if env[i] > threshold * 1.5 and env[i] >= env[i - 1] and env[i] > env[i + 1] and i - last_peak >= 6:
            peaks += 1
            last_peak = i
    rate = peaks / speech_time if speech_time > 0 else 0.0

    level_db = float(20 * np.log10(max(1e-5, np.mean(rms[speech]))))

    energy = _clamp((level_db + 35) / 20)
    variety = _clamp(pitch_std_st / 4.0)
    pace = _clamp((rate - 2.0) / 4.0)
    arousal = _clamp(0.4 * energy + 0.3 * variety + 0.3 * pace)
    hesitation = _clamp(2.0 * pause_ratio + (0.3 if longest_pause > 0.8 else 0.0))
    valence = max(-0.3, min(0.3, 0.5 * (variety - 0.35) + 0.4 * (energy - 0.45) - 0.4 * hesitation))

    return {
        "duration": round(len(x) / sr, 2), "level_db": round(level_db, 1),
        "pitch_hz": round(pitch_mean, 1), "pitch_var_st": round(pitch_std_st, 2),
        "rate": round(rate, 2), "pause_ratio": round(pause_ratio, 3), "longest_pause": round(longest_pause, 2),
        "arousal": round(arousal, 3), "valence": round(valence, 3), "hesitation": round(hesitation, 3),
    }


def analyze_wav(path):
    try:
        samples, sr = read_wav(path)
    except (OSError, wave.Error):
        return None
    return analyze_samples(samples, sr)


def with_fillers(cues, text):
    """Fold the words in: 'um... I don't know' is hesitant however smoothly it was said."""
    if cues is None:
        return None
    n = len(FILLERS.findall(text or ""))
    if n:
        cues = dict(cues)
        cues["hesitation"] = round(_clamp(cues["hesitation"] + 0.2 * n), 3)
    return cues


def describe(cues):
    """A few words for how someone sounded, or "" if unremarkable."""
    if not cues:
        return ""
    words = []
    if cues["hesitation"] > 0.4:
        words.append("hesitant")
    if cues["arousal"] > 0.7:
        words.append("animated")
    elif cues["arousal"] < 0.25:
        words.append("quiet and subdued")
    if cues["rate"] > 5.5:
        words.append("in a hurry")
    elif 0 < cues["rate"] < 2.2:
        words.append("slow")
    if cues["pitch_var_st"] < 0.8 and cues["pitch_hz"] > 0:
        words.append("flat")
    return ", ".join(words)


# ---------------------------------------------------------------- speaking

def prosody_for(mood, drives=None, hour=12.0, rng=random):
    """Piper's controls for how she should sound right now."""
    v, a = mood.valence, mood.arousal
    sleepy = drives.sleepiness(hour) if drives is not None else 0.0
    length = 1.0 - 0.12 * (a - 0.3) / 0.7 + 0.18 * max(0.0, sleepy - 0.4) + (0.08 if v < -0.2 else 0.0)
    noise = 0.667 + 0.25 * (a - 0.3) / 0.7 - (0.1 if sleepy > 0.75 else 0.0)
    noise_w = 0.8 + 0.2 * (a - 0.3) / 0.7
    silence = 0.2 + 0.35 * max(0.0, sleepy - 0.4) + (0.15 if v < -0.3 else 0.0)
    return {
        "length_scale": round(max(0.85, min(1.35, length * rng.uniform(0.97, 1.03))), 3),
        "noise_scale": round(max(0.4, min(0.95, noise * rng.uniform(0.95, 1.05))), 3),
        "noise_w_scale": round(max(0.5, min(1.0, noise_w)), 3),
        "sentence_silence": round(max(0.1, min(0.8, silence)), 2),
    }


def piper_args(prosody):
    """The prosody dict as command-line flags for KIDA's piper binary (the C++
    /usr/bin/piper, which spells them with underscores - see its --output_file)."""
    return [
        "--length_scale", str(prosody["length_scale"]),
        "--noise_scale", str(prosody["noise_scale"]),
        "--noise_w", str(prosody["noise_w_scale"]),
        "--sentence_silence", str(prosody["sentence_silence"]),
    ]
