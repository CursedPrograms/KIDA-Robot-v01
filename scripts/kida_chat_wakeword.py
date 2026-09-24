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

import numpy as np
import scipy.io.wavfile as wav

from hailo_whisper_pipeline import HailoWhisperPipeline
from common.audio_utils import load_audio
from common.preprocessing import preprocess, improve_input_audio
from common.postprocessing import clean_transcription
from common.record_utils import record_audio, SAMPLE_RATE as MIC_SAMPLE_RATE
from queue import Queue

import state
from state import VoiceMode
import voice_engine

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────

WHISPER_VARIANT  = "base"
WHISPER_DURATION = 8       # seconds for full command recording
WAKE_DURATION    = 5       # seconds for wake-word snippet
WAKE_OVERLAP     = 0.5     # seconds of prior snippet carried into the next scan,
                           # so a wake word spoken across a window boundary isn't split/lost

BASE_DIR     = Path(__file__).resolve().parent.parent   # Kida-Robot/
SCRIPTS_DIR  = BASE_DIR / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(BASE_DIR))

ENCODER_HEF = str(BASE_DIR / "resources/hefs/h8l/base/base-whisper-encoder-5s_h8l.hef")
DECODER_HEF = str(BASE_DIR / "resources/hefs/h8l/base/base-whisper-decoder-fixed-sequence-matmul-split_h8l.hef")

OLLAMA_MODEL    = "qwen2.5:0.5b"
LLM_MAX_TOKENS  = 120
LLM_TEMPERATURE = 0.95

# ── Inner life (kida_mind) ── mood, needs, memory, initiative.
# Optional: if it can't load, mind_host.MIND is None and everything below
# behaves exactly as it did before.
import kida_mind_host as mind_host
if mind_host.mind_llm is not None:
    mind_host.mind_llm.configure(model=OLLAMA_MODEL)

PIPER_BIN    = "/usr/bin/piper"
PIPER_MODEL  = str(BASE_DIR / "resources/tts/en_US-hfc_female-medium.onnx")
AUDIO_PATH   = str(BASE_DIR / "audio" / "snippets" / "sampled_audio.wav")

# Wake word variants (all lowercase for matching)
WAKE_WORDS = {
    "kida", "hi kida", "hey kida", "okay kida", "ok kida",
    "kira", "hi kira", "hey kira", "okay kira", "ok kira",
    "robot", "hi robot", "hey robot", "okay robot", "ok robot",
}

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
    # Share the physical Hailo-8L instead of claiming it exclusively, so a
    # concurrent HailoAsyncInference (group_id="SHARED") from another mode
    # can run alongside it — otherwise its VDevice() fails with
    # HAILO_OUT_OF_PHYSICAL_DEVICES the moment that mode is entered.
    multi_process_service=True,
)
print("✅ Hailo-8L Whisper ready")


# ─────────────────────────────────────────────
#  STT helper — shared transcribe core
# ─────────────────────────────────────────────

# Guards every whisper_pipeline.send_data()/get_transcription() call — the
# pipeline is a single Hailo-8L inference session, not safe to drive from
# two threads at once. Needed once transcribe_file() (below) gave the web
# HUD's voice-upload endpoint a second entry point into this same pipeline,
# running on a Flask worker thread concurrently with this module's own
# main-loop thread.
_whisper_lock = threading.Lock()


def _run_transcription(audio_path: str) -> str:
    """Run Hailo Whisper on an already-recorded audio file. ffmpeg (via
    common.audio_utils.load_audio) decodes whatever format it's given, so
    the caller doesn't need to pre-convert anything."""
    with _whisper_lock:
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


def transcribe_file(path: str) -> str:
    """Transcribe an already-recorded audio file (any format ffmpeg can
    decode — webm/ogg/wav/whatever a browser's MediaRecorder produces).

    Used by the web HUD's voice-upload endpoint: a workaround for the
    robot's own USB mic being too quiet (see the wake-word mic session) —
    record on a phone/laptop's own mic instead and upload the clip. Strips
    a leading wake word the same way transcribe() does, then hands off to
    submit_text() so it can't race the live wake-word/command loop.
    """
    text = _strip_wake_word(_run_transcription(path))
    if text:
        submit_text(text)
    return text


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
    tail = np.zeros(0, dtype="float32")
    overlap_samples = int(WAKE_OVERLAP * MIC_SAMPLE_RATE)
    while True:
        try:
            audio_data = record_audio(WAKE_DURATION, audio_path=AUDIO_PATH)
            # Prepend the tail of the previous window so a wake word spoken
            # across a scan-window boundary still appears whole in one transcription.
            combined = np.concatenate([tail, audio_data])
            wav.write(AUDIO_PATH, MIC_SAMPLE_RATE, (combined * 32767).astype(np.int16))
            tail = audio_data[-overlap_samples:] if len(audio_data) > overlap_samples else audio_data

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

def _camera_context() -> str:
    """Build a short context string from current YOLO detections + ambient
    face emotion (see face_emotion_mode.py)."""
    parts = []
    try:
        import state
        labels = state.detection_labels
        if labels:
            items = ", ".join(f"{n}({c:.0%})" for n, c in labels[:6])
            parts.append(f"[Camera sees: {items}]")

        emotion = getattr(state, "detected_emotion", None)
        if emotion:
            label, conf = emotion
            parts.append(
                f"[You notice the user's face currently reads {label} ({conf:.0%}) "
                f"— let that color your tone in this reply.]"
            )
    except Exception:
        pass
    return (" ".join(parts) + " ") if parts else ""


def ask_llm(prompt: str, context: str = "", num_predict: int = LLM_MAX_TOKENS) -> str:
    """context: her inner state for this reply (mind.pre_reply) — mood, needs,
    memories that come to mind, her views, how you sounded."""
    try:
        ctx = _camera_context()
        full_prompt = ctx + prompt if ctx else prompt
        system = SYSTEM_PROMPT
        if mind_host.MIND is not None:
            system += mind_host.mind_facts.memory_prompt_block()
        if context:
            system += "\n\n" + context
        messages = [
            {"role": "system", "content": system},
            {"role": "user",   "content": full_prompt},
        ]
        if mind_host.mind_llm is not None:
            # the mind's client: one generation at a time, so a reply never
            # races her reflection for the model
            reply = mind_host.mind_llm.chat(messages, num_predict=num_predict,
                                            temperature=LLM_TEMPERATURE) or ""
        else:
            response = ollama.chat(
                model=OLLAMA_MODEL,
                messages=messages,
                options={
                    "num_predict": num_predict,
                    "temperature": LLM_TEMPERATURE,
                },
            )
            reply = response["message"]["content"]
        reply = reply.strip()
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


def speak(text: str, key: str | None = None):
    """Speak text via Piper.

    Pass `key` for fixed/canned lines (wake acks, greetings, etc.) so the
    synthesized audio is cached as audio/voiceovers/<key>.mp3 and reused on
    future calls instead of re-running Piper every time. Dynamic text (LLM
    replies) should omit `key` since it's different every call and caching
    it would just fill the voiceovers directory with one-off files.
    """
    expression_match = re.search(r"\b(wink|smile|frown|blush)\b", text, re.I)
    expression = expression_match.group(1).lower() if expression_match else None

    spoken = re.sub(r"\b(wink|smile|frown|blush)\b", "", text, flags=re.I)
    spoken = spoken.replace("*", "").strip()

    if expression:
        print(f"😊 Expression: {expression}")
    print(f"🔊 KIDA: {spoken}")

    if not spoken:
        return expression

    if key:
        cache_path = os.path.join(voice_engine.VOICE_DIR, f"{key}.mp3")
        if os.path.isfile(cache_path) or voice_engine.synthesize(spoken, cache_path):
            voice_engine.play_file(cache_path, block=True)
        else:
            print("⚠️ TTS error: cached synthesis failed")
        return expression

    try:
        if _piper_available():
            prosody = []
            if mind_host.MIND is not None:
                try:   # sleepy, excited, down: her mood shapes how she sounds
                    prosody = mind_host.mind_voice.piper_args(mind_host.MIND.prosody())
                except Exception:
                    prosody = []
            # Lines she says more than once (the mind's remarks, boundaries,
            # reminders, the time...) come from voice_engine's repeat-line
            # cache instead of running Piper again; one-off replies are
            # rendered to a temp file as before.
            path, is_temp = voice_engine.render(spoken, prosody)
            if path is None:
                raise RuntimeError("Piper couldn't render the line")

            subprocess.run(
                ["aplay", path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if is_temp:
                os.unlink(path)

    except Exception as e:
        print(f"⚠️ TTS error: {e}")

    return expression


# ─────────────────────────────────────────────
#  Task queue
# ─────────────────────────────────────────────

_task_queue: Queue = Queue()


def submit_text(text: str) -> None:
    """Feed text straight into the same voice_commands→LLM→speak pipeline
    _task_worker() already serializes voice transcriptions through — used
    by ui.py's typed-message box and the web HUD's voice-upload endpoint so
    neither ever calls ask_llm()/speak() concurrently with the live voice
    thread (both would otherwise be able to overlap Piper/aplay playback
    or fire ollama.chat() calls at the same time)."""
    if text and text.strip():
        _task_queue.put(("user", text.strip(), None))


def say(text: str) -> None:
    """Something KIDA decided to say on her own (her inner life's initiative,
    or a reminder) — queued behind any reply in progress."""
    if text and text.strip():
        _task_queue.put(("say", text.strip(), None))


def _handle(text: str, cues) -> None:
    """One thing the user said (or typed): robot command, or conversation."""
    mind = mind_host.MIND
    if text.lower() in ("quit", "exit", "shutdown", "power off"):
        speak("Going dark. Goodbye, commander.", key="shutdown_goodbye")
        mind_host.stop()
        whisper_pipeline.stop()
        os._exit(0)
    if not text or text in ("[Silence]", ""):
        return

    mind_host.note_activity("voice")
    morning = mind_host.wake(blocking=True)   # talking to her wakes her
    if morning:
        speak(morning)

    # ── Robot control commands (handled without LLM) ──────────────────
    try:
        import voice_commands
        action = voice_commands.dispatch(text)
        if action and voice_commands.execute(action, speak):
            if mind:
                mind.note_interaction()   # still company, and an answer to whatever she said last
            return
    except Exception as e:
        print(f"⚠️ Voice command dispatch error: {e}")

    # ── Her own boundaries, care and self-knowledge come before the LLM ──
    pre = mind.pre_reply(text, cues) if mind else None
    if pre is not None and pre.reply:
        state.last_exchange = {"you": text, "kida": pre.reply, "ts": time.time()}
        speak(pre.reply)
        mind.post_reply(pre.reply)
        return
    if mind:
        for kind, fact in mind_host.mind_facts.extract_memories(text):
            if mind_host.mind_facts.remember(kind, fact) == "milestone":
                print(f"🧠 Milestone: {fact}")

    # ── Fall through to LLM for conversation ──────────────────────────
    reply = ask_llm(text,
                    context=pre.context if pre else "",
                    num_predict=mind.token_budget(LLM_MAX_TOKENS) if mind else LLM_MAX_TOKENS)
    if pre is not None and pre.preface:
        reply = f"{pre.preface} {reply}"
    state.last_exchange = {"you": text, "kida": reply, "ts": time.time()}
    speak(reply)
    if mind:
        mind.post_reply(reply)


def _task_worker():
    while True:
        kind, text, cues = _task_queue.get()
        try:
            with mind_host.busy():
                if kind == "say":
                    speak(text)
                else:
                    _handle(text, cues)
        except Exception as e:
            print(f"⚠️ Task error: {e}")
        finally:
            _task_queue.task_done()


threading.Thread(target=_task_worker, daemon=True).start()


# ─────────────────────────────────────────────
#  Main loop
# ─────────────────────────────────────────────

def _voice_cues():
    """How the last recording sounded (loudness, pitch, pace, pauses) — it
    colours how the mind reads the moment, on top of the words."""
    if mind_host.MIND is None:
        return None
    try:
        cues = mind_host.mind_voice.analyze_wav(AUDIO_PATH)
        if cues:
            print(f"🎚️  Voice: {mind_host.mind_voice.describe(cues) or 'ordinary'}")
        return cues
    except Exception:
        return None


def main():
    print("🤖 KIDA online. Waiting for wake word.")
    speak("KIDA online. Say my name when you need me, hotshot.", key="online_greeting")
    # Her inner life: needs, mood, memory, and the urge to speak first.
    mind_host.start(say)

    while True:
        try:
            # ── Phase 1: sleep until wake word (skipped in ALWAYS_ON mode) ─────
            if state.voice_mode == VoiceMode.WAKEWORD:
                wait_for_wake_word()
                # ── Phase 2: acknowledge + listen for command ──────────────────
                with mind_host.busy():
                    morning = mind_host.wake(blocking=True)   # her name wakes her
                    if morning:
                        speak(morning)
                    else:
                        speak("Yeah? I'm listening.", key="wake_ack")

            # After a wake word she's attending to you; in ALWAYS_ON she's
            # always listening, which mustn't count as busy or she'd never
            # speak up on her own.
            if state.voice_mode == VoiceMode.WAKEWORD:
                with mind_host.busy():
                    text = transcribe()
            else:
                text = transcribe()
            cues = _voice_cues() if text else None

            if not text or text in ("[Silence]", ""):
                if state.voice_mode == VoiceMode.WAKEWORD:
                    print("💨 No command heard — going back to sleep")
                    speak("I heard nothing. Going back to sleep.", key="no_command_heard")
                else:
                    print("💨 Silence — listening again")
                continue

            # ── Phase 3: process + respond ────────────────────────────────────
            _task_queue.put(("user", text, cues))
            _task_queue.join()

            # ── Phase 4: back to sleep (WAKEWORD) / keep listening (ALWAYS_ON) ──
            if state.voice_mode == VoiceMode.WAKEWORD:
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