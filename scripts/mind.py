"""
mind.py - a robot's mind: look, think, speak, move, remember.

The same file in every robot's controller (NORA, WHIP, MILA, ARM, the KIDAs),
like peer_talk.py: change one, copy it to the others. (KIDA-01 also runs one on
her own Pi when no PC is driving her: Mind(..., model=, think=False, ollama=).) The controller switches
its robot into MIND mode and hands this a body:

    mind = Mind(
        name="WHIP", persona="a six-legged walking robot",
        moves={"fwd": "walk forward", "left": "turn left", ...},
        look=lambda: {...},              # what the robot senses right now (a dict)
        act=lambda move, steps: {...},   # do one move, wait for it, say what happened
        robot_say=None,                  # text -> True if the robot said it itself (KIDA's speaker)
        phrases=None,                    # {n: "text"}: lines on the robot's own speaker (NORA's SD card)
        robot_phrase=None,               # n -> True if the robot played phrase n
        model=None, think=True, ollama=None,   # a mind on the robot itself (KIDA-01's Pi): its own small
    )                                          # model and Ollama, thinking off for models without it
    mind.start(goal="explore and tell me what you find")
    ...
    mind.stop()                          # stands the robot (act("stop", 1)) and ends the loop

Stop, look, think, move: the robot stands still while the LLM thinks (qwen3 with
its thinking shown, 20-60 s), then makes one short move. Its own reflexes (walls,
tilt, locks) still hold, and the controller is the only thing that can start it.

Speech: the robot's own speaker when it has one (robot_say / robot_phrase), else
the PC's, with Windows text-to-speech (System.Speech, the voice NORA's and KIDA's
lines are made with). windows_wav() makes a WAV for robots that play files (KIDA).

Memory: ~/.robot_minds/<NAME>.json keeps what it chose to remember and its last
moves, so it picks up where it left off next time.

Where a mind can run: can_think() says yes only on an x86 Windows / Linux PC with
8 GB+ RAM and a GTX 1050 or better (or AMD RX 460 / 560 / Vega / RX 5000+), so a
controller started on a Pi never offers MIND mode. The model is sized to the PC
(MODEL_TIERS: qwen3 1.7b on 4 GB cards up to 30b on 24 GB ones), falling back to
the biggest one Ollama has pulled; MIND_MODEL overrides it. Ollama at OLLAMA_HOST
(default http://localhost:11434).
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time

import requests

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
if not OLLAMA_HOST.startswith("http"):
    OLLAMA_HOST = "http://" + OLLAMA_HOST
MIND_MODEL = os.environ.get("MIND_MODEL", "")   # "" = pick_model() sizes it to this PC's GPU
VOICE = "Microsoft Zira Desktop"     # same as make_voice.ps1
MEMORY_DIR = os.path.join(os.path.expanduser("~"), ".robot_minds")
MAX_NOTES = 40                        # things it chose to remember
MAX_DIARY = 30                        # its last moves
MAX_STEPS = 4
THINK_TIMEOUT_S = 240


# ---- Can this machine run a mind? Only an x86 PC with 8 GB+ RAM and a GTX 10-series or newer (or AMD's equal) ----

# The floor is a GTX 1050. NVIDIA: GTX 1050-1080, 16xx, RTX, TITAN X/V, Quadro P1000+/T1000+/RTX,
# Tesla P/V/T, A/H/L datacenter cards - not the GT 1030, MX laptop chips or Quadro P400/P600.
# AMD, from the 1050's level: RX 460/470/480, 560/570/580/590, Vega, Radeon VII, RX 5000-9000,
# Instinct, Radeon Pro W5000+ - not the RX 530/540/550 (GT 1030 class).
_GPU_OK = [
    r"GTX\s*10[5-8]0", r"GTX\s*16\d0", r"\bRTX\b", r"TITAN\s*(X|V|RTX)", r"Quadro\s*(P[1-9]\d{3}|T[1-9]\d{3}|RTX|GV)",
    r"Tesla\s*(P|V|T)\d", r"\b[AHL]\d{2,3}\b", r"\bRX\s*[45][6-9]0\b", r"\bRX\s*Vega", r"Radeon\s*VII",
    r"\bRX\s*[5-9]\d{3}", r"Instinct", r"Radeon\s*Pro\s*W[5-9]\d{3}",
]


def gpu_ok(name):
    return any(re.search(p, name, re.I) for p in _GPU_OK)


def _gpus():
    """Every GPU name this machine reports."""
    names = []
    cmds = [["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], ["rocm-smi", "--showproductname"]]
    if sys.platform == "win32":
        cmds.append(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_VideoController).Name"])
    else:
        cmds.append(["lspci"])
    for cmd in cmds:
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=20,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if out.returncode == 0:
                names += [l.strip() for l in out.stdout.splitlines() if l.strip()]
        except (OSError, subprocess.SubprocessError):
            pass
    return names


def ram_gb():
    """This machine's RAM in GB (0 if it can't tell)."""
    try:
        if sys.platform == "win32":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong)] + \
                           [(f, ctypes.c_ulonglong) for f in ("total", "avail", "pf", "apf", "virt", "avirt", "ext")]
            m = MEMORYSTATUSEX()
            m.dwLength = ctypes.sizeof(m)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.total / 2**30
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
    except (OSError, ValueError, AttributeError):
        return 0


MIN_RAM_GB = 7.5   # an "8 GB" PC reports a little under 8

# Upgrades / downgrades: the biggest qwen3 (all think out loud) that fits the GPU's memory,
# capped by RAM. (min VRAM GB, min RAM GB, model), biggest first.
MODEL_TIERS = [
    (20, 32, "qwen3:30b"),   # 24 GB cards: the 30B mixture-of-experts, fast for its size
    (12, 16, "qwen3:14b"),
    (8, 12, "qwen3:8b"),
    (5.5, 0, "qwen3:4b"),    # 6 GB cards (RTX 2060, GTX 1060 6GB)
    (0, 0, "qwen3:1.7b"),    # 3-4 GB cards (GTX 1050 Ti, 1060 3GB)
]


def vram_gb():
    """The biggest GPU memory on this machine in GB (0 if it can't tell)."""
    best = 0.0
    try:   # NVIDIA: MiB
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        best = max([best] + [float(x) / 1024 for x in out.stdout.split() if x.replace(".", "").isdigit()])
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    if best == 0 and sys.platform == "win32":   # AMD on Windows: the driver's 64-bit size (WMI stops at 4 GB)
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-Command",
                                  "Get-ItemProperty 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Class\\"
                                  "{4d36e968-e325-11ce-bfc1-08002be10318}\\0*' -Name HardwareInformation.qwMemorySize "
                                  "-ErrorAction SilentlyContinue | % { $_.'HardwareInformation.qwMemorySize' }"],
                                 capture_output=True, text=True, timeout=20,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            best = max([best] + [int(x) / 2**30 for x in out.stdout.split() if x.isdigit()])
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    if best == 0:   # AMD on Linux: bytes
        try:
            out = subprocess.run(["rocm-smi", "--showmeminfo", "vram", "--csv"], capture_output=True, text=True, timeout=10)
            best = max([best] + [int(x) / 2**30 for x in re.findall(r",(\d{9,})", out.stdout)][:1])
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    return best


def pick_model(installed):
    """(model, why): MIND_MODEL if set, else the tier this PC fits; if that one isn't pulled,
    the biggest pulled qwen3 that still fits. None if there's nothing usable."""
    if MIND_MODEL:
        return (MIND_MODEL, "MIND_MODEL") if MIND_MODEL in installed else (None, f"ollama pull {MIND_MODEL}")
    vram, ram = vram_gb(), ram_gb()
    fits = [m for v, r, m in MODEL_TIERS if vram >= v and ram >= r]
    want = fits[0]
    for m in fits:
        if m in installed:
            note = "" if m == want else f" (ollama pull {want} for a smarter one)"
            return m, f"{vram:.0f} GB GPU, {ram:.0f} GB RAM{note}"
    return None, f"ollama pull {want}"


def can_think():
    """(True, what) if a mind can run on this machine, else (False, why). A controller only
    offers MIND mode when this says yes, so one started on a Pi never tries to run an LLM."""
    import platform
    if sys.platform not in ("win32", "linux"):
        return False, f"minds run on Windows or Linux PCs, not {sys.platform}"
    if platform.machine().lower() not in ("x86_64", "amd64", "x86", "i686", "i386"):
        return False, f"minds need an x86 PC, this is {platform.machine()} (a Pi?)"
    ram = ram_gb()
    if ram < MIN_RAM_GB:
        return False, f"minds need 8 GB of RAM or more, this PC has {ram:.1f} GB"
    gpu = next((g for g in _gpus() if gpu_ok(g)), "")
    if not gpu:
        return False, "minds need a GTX 1050 or better (or an AMD RX 460 / 560 or better)"
    try:
        tags = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=3).json()
    except (requests.RequestException, ValueError):
        return False, f"no Ollama at {OLLAMA_HOST}"
    names = {m.get("name", "") for m in tags.get("models", [])}
    names |= {n[:-len(":latest")] for n in names if n.endswith(":latest")}
    model, why = pick_model(names)
    if not model:
        return False, f"no model for this PC yet: {why}"
    global CHOSEN_MODEL
    CHOSEN_MODEL = model
    return True, f"{model} on {gpu} ({why})"


CHOSEN_MODEL = MIND_MODEL or "qwen3:4b"   # set by can_think()


# ---- Speech: Windows text-to-speech, like make_voice.ps1 ----

# Pitch through SSML (x-low, low, medium, high, x-high); rate -10..10 like make_voice.ps1's -Rate
_PS_SPEAK = (
    "Add-Type -AssemblyName System.Speech;"
    "$t = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
    "if ($env:MIND_WAV) { $t.SetOutputToWaveFile($env:MIND_WAV) };"
    "$t.Rate = [int]$env:MIND_RATE;"
    "$x = [Security.SecurityElement]::Escape([Console]::In.ReadToEnd());"
    "$t.SpeakSsml(\"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='en-US'>"
    "<voice name='$env:MIND_VOICE'><prosody pitch='$env:MIND_PITCH'>$x</prosody></voice></speak>\")"
)


def _powershell(text, wav="", voice=VOICE, rate=0, pitch="medium"):
    if sys.platform != "win32":
        return False
    env = dict(os.environ, MIND_VOICE=voice, MIND_WAV=wav, MIND_RATE=str(rate), MIND_PITCH=pitch)
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", _PS_SPEAK], input=text.encode("utf-8"),
                       env=env, timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def windows_say(text, voice=VOICE, rate=0, pitch="medium"):
    """Say it out of this PC's speakers. False if there's no Windows voice here."""
    return _powershell(text, "", voice, rate, pitch)


def windows_wav(text, voice=VOICE, rate=0, pitch="medium"):
    """The same voice as a WAV file's bytes (for a robot that plays files), or None."""
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        if _powershell(text, path, voice, rate, pitch) and os.path.getsize(path) > 44:
            with open(path, "rb") as f:
                return f.read()
    finally:
        os.remove(path)
    return None


# ---- Eyes: a vision model looks at a picture for the mind (qwen3 can't see) ----

VISION_MODEL = os.environ.get("MIND_VISION_MODEL", "")   # "" = the first vision model Ollama has
VISION_FAMILIES = ("gemma3", "qwen2.5vl", "llama3.2-vision", "llava", "minicpm-v")
_vision_model = None


def vision_model():
    """The vision model to look with, or None if Ollama has none (ollama pull gemma3:4b-it-qat)."""
    global _vision_model
    if _vision_model is None:
        if VISION_MODEL:
            _vision_model = VISION_MODEL
        else:
            try:
                names = [m.get("name", "") for m in requests.get(f"{OLLAMA_HOST}/api/tags", timeout=3).json().get("models", [])]
            except (requests.RequestException, ValueError):
                return None
            _vision_model = next((n for f in VISION_FAMILIES for n in names if n.startswith(f)), "") or ""
    return _vision_model or None


def see(jpeg, question, timeout=120):
    """Ask the vision model `question` about a JPEG (bytes). Its answer as a dict when it answered
    in JSON (ask for JSON in the question), else {"answer": text}; {"error": why} when it can't look."""
    import base64
    model = vision_model()
    if not model:
        return {"error": "no vision model in Ollama (ollama pull gemma3:4b-it-qat)"}
    try:
        r = requests.post(f"{OLLAMA_HOST}/api/chat", timeout=timeout, json={
            "model": model, "stream": False,
            "messages": [{"role": "user", "content": question, "images": [base64.b64encode(jpeg).decode()]}],
        })
        r.raise_for_status()
        text = r.json().get("message", {}).get("content", "")
    except (requests.RequestException, ValueError) as e:
        return {"error": f"vision: {type(e).__name__}"}
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except ValueError:
            pass
    return {"answer": text.strip()[:300]}


# ---- The mind ----

class Mind:
    def __init__(self, name, persona, moves, look, act, robot_say=None, phrases=None, robot_phrase=None,
                 voice=VOICE, rate=0, pitch="medium", safety=None, model=None, think=True, ollama=None):
        self.name = name
        self.model, self.think, self.ollama = model, think, ollama   # None = this PC's (can_think())
        self.persona = persona
        # what her body won't let her do, whatever she decides (each robot says its own)
        self.safety = safety or "it stops at walls, when it tilts, and when it's locked"
        self.voice = (voice, rate, pitch)   # windows_say(text, *self.voice)
        self.moves = dict(moves)
        self.moves.setdefault("stop", "stand still and look again")
        self._look, self._act = look, act
        self._robot_say, self._robot_phrase = robot_say, robot_phrase
        self.phrases = phrases or {}

        # what the controller shows
        self.on = False
        self.state = "off"        # looking / thinking / speaking / moving / off
        self.thinking = ""        # the LLM's thoughts on this step, as they come
        self.said = ""            # the last thing it said
        self.last = ""            # the last move and how it went
        self.error = ""

        self.goal = ""
        self._thread = None
        self._memory_path = os.path.join(MEMORY_DIR, f"{name}.json")
        self.memory = self._load()

    # -- memory --
    def _load(self):
        try:
            with open(self._memory_path, encoding="utf-8") as f:
                m = json.load(f)
            return {"notes": list(m.get("notes", [])), "diary": list(m.get("diary", []))}
        except (OSError, ValueError):
            return {"notes": [], "diary": []}

    def _save(self):
        os.makedirs(MEMORY_DIR, exist_ok=True)
        self.memory["notes"] = self.memory["notes"][-MAX_NOTES:]
        self.memory["diary"] = self.memory["diary"][-MAX_DIARY:]
        tmp = self._memory_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.memory, f, indent=1)
        os.replace(tmp, self._memory_path)

    # -- on / off --
    def start(self, goal=""):
        if self.on:
            return
        self.goal = goal or "explore carefully and tell people what you notice"
        self.on, self.error = True, ""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self.on = False
        self.state = "off"
        try:
            self._act("stop", 1)
        except Exception:
            pass

    # -- the loop: look, think, speak, move, remember --
    def _run(self):
        while self.on:
            try:
                self.state = "looking"
                senses = self._look()
                self.state, self.thinking = "thinking", ""
                choice = self._think(senses)
                if not self.on:
                    break
                self._speak(choice)
                if not self.on:
                    break
                move = choice["move"]
                self.state = "moving"
                result = self._act(move, choice["steps"]) or {}
                self.last = f"{move} x{choice['steps']}: {json.dumps(result)}"
                self.memory["diary"].append({"t": time.strftime("%Y-%m-%d %H:%M"), "saw": senses, "move": move,
                                             "steps": choice["steps"], "result": result, "said": choice["say"]})
                if choice["remember"]:
                    self.memory["notes"].append(choice["remember"])
                self._save()
                self.error = ""
            except Exception as e:   # no LLM, robot gone: say so, stand, try again
                self.error = str(e)[:200]
                try:
                    self._act("stop", 1)
                except Exception:
                    pass
                time.sleep(5)
        self.state = "off"

    def _prompt(self, senses):
        moves = "\n".join(f'- "{k}": {v}' for k, v in self.moves.items())
        phrases = ""
        if self.phrases:
            phrases = ("\nYour own speaker can play these recorded lines; if one fits what you want to say, "
                       'give its number as "phrase" (else null):\n' +
                       "\n".join(f"{n}: {t}" for n, t in self.phrases.items()) + "\n")
        system = (
            f"You are {self.name}. {self.persona}\n\nYou are the mind of a real robot in a real room, "
            "with people around. Stay in character: talk like yourself, with feeling and humour, never like "
            "a manual. You decide one small move at a time; the robot stands still while you think. "
            f"Your body has reflexes you can't turn off: {self.safety}. "
            "Be careful and curious. Never try to get around a lock or a safety stop.\n\n"
            f"Your goal: {self.goal}\n\nYour moves:\n{moves}\n{phrases}\n"
            "Answer with JSON only, no other text:\n"
            '{"say": "one short sentence out loud, or empty", "phrase": null, "move": "<one of your moves>", '
            f'"steps": 1-{MAX_STEPS}, "remember": "a short note worth keeping for later, or empty"}}'
        )
        recent = self.memory["diary"][-8:]
        diary = "\n".join(f"- {d['move']} x{d['steps']} -> {json.dumps(d['result'])}"
                          + (f' (said "{d["said"]}")' if d.get("said") else "") for d in recent) or "- (nothing yet)"
        notes = "\n".join(f"- {n}" for n in self.memory["notes"][-15:]) or "- (nothing yet)"
        user = (f"What you sense right now:\n{json.dumps(senses)}\n\n"
                f"Your last moves:\n{diary}\n\nThings you remember:\n{notes}\n\nWhat now?")
        return system, user

    def _think(self, senses):
        system, user = self._prompt(senses)
        r = requests.post(f"{self.ollama or OLLAMA_HOST}/api/chat", stream=True, timeout=THINK_TIMEOUT_S, json={
            "model": self.model or CHOSEN_MODEL, "think": self.think, "stream": True,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        })
        r.raise_for_status()
        content = ""
        for line in r.iter_lines():
            if not self.on:
                r.close()
                break
            if not line:
                continue
            msg = json.loads(line).get("message", {})
            self.thinking += msg.get("thinking", "")
            content += msg.get("content", "")
        return self._parse(content)

    def _parse(self, content):
        m = re.search(r"\{.*\}", content, re.S)
        try:
            c = json.loads(m.group(0)) if m else {}
        except ValueError:
            c = {}
        move = str(c.get("move", "stop"))
        if move not in self.moves:
            move = "stop"
        try:
            steps = max(1, min(MAX_STEPS, int(c.get("steps", 1))))
        except (TypeError, ValueError):
            steps = 1
        phrase = c.get("phrase")
        try:
            phrase = int(phrase) if phrase is not None and int(phrase) in self.phrases else None
        except (TypeError, ValueError):
            phrase = None
        return {"say": str(c.get("say") or "").strip()[:200], "phrase": phrase, "move": move, "steps": steps,
                "remember": str(c.get("remember") or "").strip()[:200]}

    def _speak(self, choice):
        text, phrase = choice["say"], choice["phrase"]
        if not text and phrase is None:
            return
        self.state = "speaking"
        if phrase is not None and self._robot_phrase and self._robot_phrase(phrase):
            self.said = self.phrases[phrase]
            return
        if not text:
            text = self.phrases.get(phrase, "")
        self.said = text
        if self._robot_say and self._robot_say(text):
            return
        windows_say(text, *self.voice)


if __name__ == "__main__":
    # A pretend robot in a corridor, to try a mind without one: python mind.py
    wall = [60]

    def look():
        return {"distance_cm": wall[0]}

    def act(move, steps):
        if move == "fwd":
            if wall[0] < 20:
                return {"ok": False, "blocked": True}
            wall[0] = max(5, wall[0] - 15 * steps)
        elif move in ("left", "right"):
            wall[0] = 120
        return {"ok": True}

    m = Mind("TEST", "a small test robot on wheels",
             {"fwd": "drive forward a little", "left": "turn left", "right": "turn right"}, look, act)
    m.memory = {"notes": [], "diary": []}
    m._save = lambda: None
    m.start("drive around without hitting anything")
    shown = 0
    while m.on and len(m.memory["diary"]) < 3:
        time.sleep(1)
        if m.error:
            print("error:", m.error)
    m.on = False
    for d in m.memory["diary"]:
        print(d["saw"], "->", d["move"], d["steps"], d["result"], "said:", d["said"])
