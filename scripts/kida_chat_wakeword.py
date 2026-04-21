# kida_chat.py
# Pipeline: Mic → Wake Word → Hailo-8L Whisper → Ollama → Piper TTS

import os
import re
import sys
import time
import threading
import subprocess
import tempfile
import warnings
import ollama
warnings.filterwarnings("ignore")
from pathlib import Path

from hailo_whisper_pipeline import HailoWhisperPipeline
from common.audio_utils import load_audio
from common.preprocessing import preprocess, improve_input_audio
from common.postprocessing import clean_transcription
from common.record_utils import record_audio
from queue import Queue

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────

WHISPER_VARIANT  = "base"
WHISPER_DURATION = 8       # seconds for full command recording
WAKE_DURATION    = 2       # seconds for wake-word snippet

BASE_DIR     = Path(__file__).resolve().parent.parent   # Kida-Robot/
SCRIPTS_DIR  = BASE_DIR / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(BASE_DIR))

ENCODER_HEF = str(BASE_DIR / "resources/hefs/h8l/base/base-whisper-encoder-5s_h8l.hef")
DECODER_HEF = str(BASE_DIR / "resources/hefs/h8l/base/base-whisper-decoder-fixed-sequence-matmul-split_h8l.hef")

OLLAMA_MODEL    = "qwen2.5:0.5b"
LLM_MAX_TOKENS  = 120
LLM_TEMPERATURE = 0.95

PIPER_BIN    = "/usr/bin/piper"
PIPER_MODEL  = str(BASE_DIR / "resources/tts/en_US-hfc_female-medium.onnx")
AUDIO_PATH   = str(BASE_DIR / "sampled_audio.wav")

# Wake word variants (all lowercase for matching)
WAKE_WORDS = {"kida", "hi kida", "hey kida", "okay kida", "ok kida"}

# Character personality
_CHAR_FILE = SCRIPTS_DIR / "character_description.txt"
try:
    SYSTEM_PROMPT = _CHAR_FILE.read_text().strip()
except FileNotFoundError:
    SYSTEM_PROMPT = (
        "You are KIDA, a flirty, sarcastic AI tank robot girl. "
        "Keep your responses clever, short, and spicy."
    )

# ─────────────────────────────────────────────
#  Hailo-8L Whisper init
# ─────────────────────────────────────────────

print(f"🔧 Loading Hailo-8L Whisper ({WHISPER_VARIANT})…")

for p in (ENCODER_HEF, DECODER_HEF):
    if not os.path.exists(p):
        print(f"❌ HEF not found: {p}")
        sys.exit(1)

whisper_pipeline = HailoWhisperPipeline(
    encoder_model_path=ENCODER_HEF,
    decoder_model_path=DECODER_HEF,
    variant=WHISPER_VARIANT,
)
print("✅ Hailo-8L Whisper ready")


# ─────────────────────────────────────────────
#  STT helper — shared transcribe core
# ─────────────────────────────────────────────

def _run_transcription(audio_path: str) -> str:
    """Run Hailo Whisper on an already-recorded WAV file."""
    audio = load_audio(audio_path)
    chunk_length = 10 if WHISPER_VARIANT == "tiny" else 5

    audio, start_time = improve_input_audio(audio, vad=True)
    chunk_offset = max(0.0, start_time - 0.2)

    mel_spectrograms = preprocess(
        audio,
        is_nhwc=True,
        chunk_length=chunk_length,
        chunk_offset=chunk_offset,
    )

    results = []
    for mel in mel_spectrograms:
        whisper_pipeline.send_data(mel)
        time.sleep(0.1)
        raw = whisper_pipeline.get_transcription()
        text = clean_transcription(raw)
        if text:
            results.append(text)

    return " ".join(results).strip()


# ─────────────────────────────────────────────
#  Wake-word listener
# ─────────────────────────────────────────────

def _contains_wake_word(text: str) -> bool:
    """Return True if any wake word phrase appears in the transcription."""
    t = text.lower().strip()
    # Exact phrase match anywhere in the string
    for ww in WAKE_WORDS:
        if ww in t:
            return True
    return False


def _strip_wake_word(text: str) -> str:
    """Remove the wake word prefix so the remainder is the actual command."""
    t = text.strip()
    # Sort by length descending so longer phrases match first
    for ww in sorted(WAKE_WORDS, key=len, reverse=True):
        # Case-insensitive removal at the start or anywhere
        pattern = re.compile(re.escape(ww) + r"[,!?.]*\s*", re.IGNORECASE)
        t = pattern.sub("", t, count=1).strip()
    return t


def wait_for_wake_word() -> None:
    """Block until the wake word is heard, then return."""
    print("😴 Sleeping… say 'Hey KIDA' to wake me up.")
    while True:
        try:
            record_audio(WAKE_DURATION, audio_path=AUDIO_PATH)
            snippet = _run_transcription(AUDIO_PATH)
            if not snippet:
                continue
            print(f"   👂 (wake scan) {snippet!r}")
            if _contains_wake_word(snippet):
                print("⚡ Wake word detected!")
                return
        except Exception as e:
            print(f"⚠️  Wake-word error: {e}")
            time.sleep(0.5)


# ─────────────────────────────────────────────
#  STT — full command transcription
# ─────────────────────────────────────────────

def transcribe(duration: int = WHISPER_DURATION) -> str:
    print(f"🎤 Listening for command… ({duration}s)")
    record_audio(duration, audio_path=AUDIO_PATH)
    full = _run_transcription(AUDIO_PATH)
    # Strip wake word if user said it again before the command
    full = _strip_wake_word(full)
    print(f"📝 Command: {full!r}")
    return full


# ─────────────────────────────────────────────
#  LLM — Ollama
# ─────────────────────────────────────────────

def ask_llm(prompt: str) -> str:
    try:
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": prompt},
            ],
            options={
                "num_predict": LLM_MAX_TOKENS,
                "temperature": LLM_TEMPERATURE,
            },
        )
        reply = response["message"]["content"].strip()
        # Strip DeepSeek-R1 chain-of-thought tags if present
        reply = re.sub(r"<think>.*?</think>", "", reply, flags=re.DOTALL).strip()
        return reply if reply else "I got lost in thought. Try again, sugar."
    except Exception as e:
        print(f"⚠️  LLM error: {e}")
        return "I'm glitching hard, babe. Try again later."


# ─────────────────────────────────────────────
#  TTS — Piper
# ─────────────────────────────────────────────

def _piper_available() -> bool:
    return os.path.isfile(PIPER_BIN) and os.path.isfile(PIPER_MODEL)


def speak(text: str):
    expression_match = re.search(r"\b(wink|smile|frown|blush)\b", text, re.I)
    expression = expression_match.group(1).lower() if expression_match else None

    spoken = re.sub(r"\b(wink|smile|frown|blush)\b", "", text, flags=re.I)
    spoken = spoken.replace("*", "").strip()

    if expression:
        print(f"😊 Expression: {expression}")
    print(f"🔊 KIDA: {spoken}")

    if not spoken:
        return expression

    try:
        if _piper_available():
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
            tmp.close()

            proc = subprocess.run(
                [PIPER_BIN, "--model", PIPER_MODEL, "--output_file", tmp.name],
                input=spoken.encode("utf-8"),
                capture_output=True,
                timeout=15,
            )

            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.decode())

            subprocess.run(
                ["aplay", tmp.name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            os.unlink(tmp.name)

    except Exception as e:
        print(f"⚠️ TTS error: {e}")

    return expression


# ─────────────────────────────────────────────
#  Task queue
# ─────────────────────────────────────────────

_task_queue: Queue = Queue()


def _task_worker():
    while True:
        text = _task_queue.get()
        if text.lower() in ("quit", "exit", "shutdown", "power off"):
            speak("Going dark. Goodbye, commander.")
            whisper_pipeline.stop()
            os._exit(0)
        if not text or text in ("[Silence]", ""):
            _task_queue.task_done()
            continue
        reply = ask_llm(text)
        speak(reply)
        _task_queue.task_done()


threading.Thread(target=_task_worker, daemon=True).start()


# ─────────────────────────────────────────────
#  Main loop
# ─────────────────────────────────────────────

def main():
    print("🤖 KIDA online. Waiting for wake word.")
    speak("KIDA online. Say my name when you need me, hotshot.")

    while True:
        try:
            # ── Phase 1: sleep until wake word ────────────────────────────────
            wait_for_wake_word()

            # ── Phase 2: acknowledge + listen for command ─────────────────────
            speak("Yeah? I'm listening.")

            text = transcribe()

            if not text or text in ("[Silence]", ""):
                print("💨 No command heard — going back to sleep")
                speak("I heard nothing. Going back to sleep.")
                continue

            # ── Phase 3: process + respond ────────────────────────────────────
            _task_queue.put(text)
            _task_queue.join()

            # ── Phase 4: back to sleep ─────────────────────────────────────────
            print("😴 Back to sleep — waiting for wake word…")

        except KeyboardInterrupt:
            print("\n👋 Shutting down…")
            whisper_pipeline.stop()
            break

        except Exception as e:
            print(f"⚠️ Loop error: {e}")
            time.sleep(1)


if __name__ == "__main__":
    main()