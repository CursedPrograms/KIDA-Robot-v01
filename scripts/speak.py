#!/usr/bin/env python3

import subprocess
import os
import sys
import argparse
import numpy as np
import sounddevice as sd

# ── CONFIG ────────────────────────────────────────────────
_SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
VOICE_MODEL  = os.path.join(_SCRIPT_DIR, "../voices/en_US-amy-medium.onnx")
PIPER_EXE = os.path.join(_SCRIPT_DIR, "../venv311/Scripts/piper.exe")
AUDIO_DEVICE = "plughw:2,0"  # Linux only
WAVES_DIR    = "/audio"
# ─────────────────────────────────────────────────────────

IS_WINDOWS = sys.platform == "win32"

def speak_stream(text: str):
    """Speak text directly — no file saved."""
    if not os.path.exists(VOICE_MODEL):
        raise FileNotFoundError(f"❌  Voice model not found: {VOICE_MODEL}")

    piper_cmd = [PIPER_EXE if IS_WINDOWS else "piper", "--model", VOICE_MODEL, "--output_raw"]

    if IS_WINDOWS and not os.path.exists(PIPER_EXE):
        raise FileNotFoundError(f"❌  Piper not found: {PIPER_EXE}")

    piper = subprocess.Popen(
        piper_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    piper.stdin.write(text.encode())
    piper.stdin.close()

    raw = piper.stdout.read()
    piper.wait()

    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    sd.play(audio, samplerate=22050)
    sd.wait()


def speak_save(text: str) -> str:
    """Speak text and save a WAV file. Returns the saved path."""
    os.makedirs(WAVES_DIR, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    # Use first 30 chars of text as part of filename
    slug = text[:30].strip().replace(" ", "_").replace("/", "-")
    wav_path = os.path.join(WAVES_DIR, f"{timestamp}_{slug}.wav")

    piper = subprocess.Popen(
        ["piper", "--model", VOICE_MODEL, "--output_file", wav_path],
        stdin=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    piper.stdin.write(text.encode())
    piper.stdin.close()
    piper.wait()

    subprocess.run(
        ["aplay", "-D", AUDIO_DEVICE, wav_path],
        stderr=subprocess.DEVNULL,
    )
    return wav_path


def main():
    parser = argparse.ArgumentParser(description="Piper TTS — type text, hear it spoken.")
    parser.add_argument("--save", action="store_true", help="Save each output as a WAV file")
    args = parser.parse_args()

    if not os.path.isfile(VOICE_MODEL):
        print(f"❌  Voice model not found: {VOICE_MODEL}")
        print("    Check VOICE_MODEL path in the CONFIG section.")
        sys.exit(1)

    mode = "stream + save to ./waves/" if args.save else "stream only"
    print("=" * 45)
    print("  🔊  Piper TTS")
    print(f"  Mode   : {mode}")
    print(f"  Voice  : {os.path.basename(VOICE_MODEL)}")
    print(f"  Device : {AUDIO_DEVICE}")
    print("  Ctrl+C to quit")
    print("=" * 45 + "\n")

    while True:
        try:
            text = input("Say: ").strip()
            if not text:
                continue

            if args.save:
                path = speak_save(text)
                print(f"   💾 Saved: {path}")
            else:
                speak_stream(text)

        except KeyboardInterrupt:
            print("\n\nBye!")
            sys.exit(0)


if __name__ == "__main__":
    main()
