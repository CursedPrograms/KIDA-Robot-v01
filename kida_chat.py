# kida_chat.py
# Pipeline: Mic → Hailo-8L Whisper → Ollama DeepSeek → Piper TTS

import os
import re
import sys
import time
import threading
import subprocess
import tempfile
import warnings
import pygame
import ollama
warnings.filterwarnings("ignore")

# ── Paths ──
SCRIPTS_DIR  = "/home/kida-01/Desktop/Kida-Robot/scripts"
PROJECT_DIR  = "/home/kida-01/Desktop/Kida-Robot"

sys.path.insert(0, SCRIPTS_DIR)
sys.path.insert(0, PROJECT_DIR)

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
WHISPER_DURATION = 5

ENCODER_HEF = "/home/kida-01/Desktop/Kida-Robot/resources/hefs/h8l/base/base-whisper-encoder-5s_h8l.hef"
DECODER_HEF = "/home/kida-01/Desktop/Kida-Robot/resources/hefs/h8l/base/base-whisper-decoder-fixed-sequence-matmul-split_h8l.hef"

#OLLAMA_MODEL    = "deepseek-r1:1.5b"
OLLAMA_MODEL = "qwen2.5:0.5b"
LLM_MAX_TOKENS  = 120
LLM_TEMPERATURE = 0.95

PIPER_BIN   = "/usr/bin/piper"
PIPER_MODEL  = "/home/kida-01/Desktop/Kida-Robot/resources/tts/en_US-hfc_female-medium.onnx"
AUDIO_PATH  = "/home/kida-01/Desktop/Kida-Robot/sampled_audio.wav"

# Character personality
_CHAR_FILE = "/home/kida-01/Desktop/Kida-Robot/scripts/character_description.txt"
try:
    with open(_CHAR_FILE) as f:
        SYSTEM_PROMPT = f.read().strip()
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
#  STT — Hailo-8L Whisper
# ─────────────────────────────────────────────

def transcribe(duration: int = WHISPER_DURATION) -> str:
    print(f"🎤 Listening... ({duration}s)")
    record_audio(duration, audio_path=AUDIO_PATH)

    audio = load_audio(AUDIO_PATH)
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

    full = " ".join(results).strip()
    print(f"📝 Heard: {full!r}")
    return full


# ─────────────────────────────────────────────
#  LLM — Ollama DeepSeek
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
        # Strip DeepSeek-R1 chain-of-thought tags
        reply = re.sub(r"<think>.*?</think>", "", reply, flags=re.DOTALL).strip()
        return reply if reply else "I got lost in thought. Try again, sugar."
    except Exception as e:
        print(f"⚠️  LLM error: {e}")
        return "I'm glitching hard, babe. Try again later."


# ─────────────────────────────────────────────
#  TTS — Piper (fallback: pyttsx3)
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
            pygame.mixer.music.load(tmp.name)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                pygame.time.Clock().tick(10)
            os.unlink(tmp.name)
        else:
            print("⚠️  Piper not found — falling back to pyttsx3")
            import pyttsx3
            engine = pyttsx3.init()
            engine.say(spoken)
            engine.runAndWait()
    except Exception as e:
        print(f"⚠️  TTS error: {e}")

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
    if not pygame.mixer.get_init():
        pygame.mixer.pre_init(44100, -16, 2, 1024)
        pygame.mixer.init()

    print("🤖 KIDA online. Awaiting orders.")
    speak("KIDA online. Ready when you are, hotshot.")

    while True:
        try:
            text = transcribe()
            if not text or text in ("[Silence]", ""):
                print("💨 Silence — listening again")
                continue
            _task_queue.put(text)
            _task_queue.join()
        except KeyboardInterrupt:
            print("\n👋 Shutting down…")
            whisper_pipeline.stop()
            break
        except Exception as e:
            print(f"⚠️  Loop error: {e}")
            time.sleep(1)


if __name__ == "__main__":
    main()