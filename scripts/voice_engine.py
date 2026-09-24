# voice_engine.py — KIDA's voice: Piper TTS synthesis + cached playback
#
# Two jobs:
#   1. Synthesize text -> mp3 via Piper (used by voice_gen.py and at runtime)
#   2. Play mp3s on a dedicated pygame Channel so voice never cuts music
#      (pygame.mixer.music is the single background-music stream; Sound +
#      Channel mixes independently on top of it)
#
# This is separate from kida_chat_wakeword.py's own speak() — that one
# handles conversational replies during a wake-word turn. This module
# handles voice that happens *outside* a conversation: mode-change
# acknowledgments (fired from keyboard/IR/web too, not just voice),
# ambient surroundings narration, and reactive alerts like vibration.

import os
import re
import subprocess
import tempfile
import threading

import pygame

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR    = os.path.dirname(_SCRIPT_DIR)
VOICE_DIR   = os.path.join(BASE_DIR, "audio", "voiceovers")

PIPER_BIN   = "/usr/bin/piper"
PIPER_MODEL = os.path.join(BASE_DIR, "resources", "tts", "en_US-hfc_female-medium.onnx")

os.makedirs(VOICE_DIR, exist_ok=True)

# ── Feature toggles ──────────────────────────────────────────────────────
VOICE_ENABLED         = True   # master switch — mute all of this module's speech
ANNOUNCE_MODES        = True   # speak the mode name on every drive-mode change
DESCRIBE_SURROUNDINGS = False  # ambient narration — off by default, enable via
                                # voice ("start narrating") or set_enabled()

_lock    = threading.Lock()
_channel = None


def _get_channel():
    global _channel
    if not pygame.mixer.get_init():
        pygame.mixer.init()
    if _channel is None:
        _channel = pygame.mixer.Channel(7)  # reserved, separate from music
    return _channel


def slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    slug = re.sub(r"[\s-]+", "_", slug)
    return slug[:40] or "line"


def _piper_available() -> bool:
    return os.path.isfile(PIPER_BIN) and os.path.isfile(PIPER_MODEL)


def synthesize(text: str, out_path: str) -> bool:
    """Render text to an mp3 at out_path via Piper + ffmpeg. Returns True on success."""
    if not _piper_available():
        print(f"⚠️ voice_engine: piper binary or model missing ({PIPER_BIN}, {PIPER_MODEL})")
        return False

    tmp_wav = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    tmp_wav.close()
    try:
        proc = subprocess.run(
            [PIPER_BIN, "--model", PIPER_MODEL, "--output_file", tmp_wav.name],
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=20,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode(errors="ignore"))

        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", tmp_wav.name,
             "-codec:a", "libmp3lame", "-qscale:a", "4", out_path],
            check=True,
        )
        return True
    except Exception as e:
        print(f"⚠️ voice_engine synth error: {e}")
        return False
    finally:
        try:
            os.unlink(tmp_wav.name)
        except OSError:
            pass


def play_file(path: str, block: bool = False) -> None:
    """Play an existing mp3/wav on the dedicated voice channel (won't cut music)."""
    try:
        sound = pygame.mixer.Sound(path)
        ch = _get_channel()
        ch.play(sound)
        if block:
            while ch.get_busy():
                pygame.time.wait(50)
    except Exception as e:
        print(f"⚠️ voice_engine playback error: {e}")


def _resolve_path(text: str, key: str | None) -> str | None:
    name = key or f"_tmp_{slugify(text)}"
    path = os.path.join(VOICE_DIR, f"{name}.mp3")
    if not os.path.isfile(path):
        if not synthesize(text, path):
            return None
    return path


def speak_line(text: str, key: str = None, block: bool = False) -> None:
    """
    Speak text out loud. If key is given, reuse/cache audio/voiceovers/<key>.mp3
    instead of re-synthesizing every time (fast + consistent for repeated lines
    like mode names). Runs in a background thread unless block=True, so callers
    like a mode-switch hook never stall waiting on synthesis.
    """
    if not VOICE_ENABLED:
        return

    def _job():
        with _lock:
            path = _resolve_path(text, key)
        if path is None:
            return
        print(f"🔊 KIDA: {text}")
        play_file(path, block=True)

    if block:
        _job()
    else:
        threading.Thread(target=_job, daemon=True).start()


# ── Mode announcements ───────────────────────────────────────────────────
_MODE_LINES = {
    "KEYBOARD":      "Keyboard mode. You're driving.",
    "IR_REMOTE":     "IR remote mode. Point and go.",
    "AUTONOMOUS":    "Autonomous mode. Try to keep up.",
    "LINE_FOLLOWER": "Line follower mode. Watch me stay on track.",
    "IDLE":          "Idle mode. Taking a break.",
    "WATCHDOG":      "Watchdog mode. I'm watching.",
    "PERSON_FOLLOW": "Follow mode. Lead the way.",
}


def announce_mode(mode) -> None:
    """Speak the mode name. Call this from any mode-switch path."""
    if not (VOICE_ENABLED and ANNOUNCE_MODES):
        return
    name = getattr(mode, "name", str(mode))
    text = _MODE_LINES.get(name, f"{name} mode.")
    speak_line(text, key=f"mode_{name.lower()}")
