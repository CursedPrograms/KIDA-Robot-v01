"""peer_talk.py - two robots with minds talking to each other, refereed by RIFT.

DREAM, KIDA-01 and TINA all run an LLM (DREAM and KIDA an inner life too),
so when RIFT pairs them up (Fleet/conversations.py) they don't just trade phrasebook chirps:

  1. RIFT asks each for a rock-paper-scissors move (GET /peer/rps) at the same
     time, so neither sees the other's. Both beep their move (talk_bf.h 14-16).
  2. The winner picks how they talk (GET /peer/choose): "words" (spoken
     sentences from the LLM) or "brainfuck" (the fleet's beeped phrasebook -
     their own language).
  3. RIFT relays a few turns (POST /peer/say). Each one carries the speaker's
     mind snapshot, so the listener answers knowing how the other feels.

The same file lives in DREAM (peer_talk.py, next to app.py), KIDA-01
(scripts/peer_talk.py) and TINA (tina/peer_talk.py); each wires in its own hooks
with PeerTalk(...) and register_routes(app). Keep the three copies the same.

The chirp-only robots (NORA, WHIP, MILA, ARM...) are untouched: RIFT keeps
chirping with them as before, and DREAM / KIDA / TINA still answer /chirp.
"""

import random
import re
import time

MOVES = ["rock", "paper", "scissors"]
MOVE_U = {m: 14 + i for i, m in enumerate(MOVES)}   # their utterances in talk_bf.h
BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}

# The phrasebook (talk_bf.h / RIFT's talk_bf.json): 0-6 phrases, 7-13 replies.
PHRASE_TEXT = ["hi", "hru?", "yay", "hm?", "zzz", "play", "bye"]
REPLY_TEXT = ["hi!", "ok:)", "yay!", "oh!", "nite", "yes!", "bye!"]
HELLO, HOW, HAPPY, CURIOUS, SLEEPY, PLAY, BYE = range(7)

TOO_SLEEPY = 0.85      # sleepiness above this: she'd rather doze than chat
LINE_CHARS = 220       # longest spoken line


def utterance_text(u):
    if u is None:
        return ""
    if 0 <= u < 7:
        return PHRASE_TEXT[u]
    if 7 <= u < 14:
        return REPLY_TEXT[u - 7]
    if 14 <= u < 17:
        return "RPS"[u - 14]
    return ""


def speech_seconds(text):
    """Roughly how long saying text aloud takes (Piper, ~2.5 words/s)."""
    return 1.0 + len(text.split()) / 2.5


class PeerTalk:
    """name: this robot ("DREAM"). persona: who she is, in a sentence, for the prompt.
    mind: her Mind (dream_mind / kida_mind) or None. generate(prompt, **kw): the LLM
    (the mind's llm.generate). add_thought(text, kind): the mind's reflection.add_thought.
    speak(text): say a line aloud in her own voice (Piper; DREAM lip-synced on her
    screen) and return once it's been said. chirp(u): start beeping a phrasebook
    utterance (RIFT times how long the program beeps).
    available(): (bool, reason) - is she free to chat (nobody around, not busy)?
    extra(): optional, more to share about her body, e.g. {"battery": 80, "mode": "patrol"}."""

    def __init__(self, name, persona, mind, generate, add_thought, speak, chirp, available, extra=None):
        self.name, self.persona, self.mind = name, persona, mind
        self.generate, self.add_thought = generate, add_thought
        self.speak, self.chirp, self._available = speak, chirp, available
        self.extra = extra
        self.session = None    # {"peer", "mode", "lines": [(who, text)], "started"}

    # ---- her state
    def snapshot(self):
        """What she shares about herself: compact, so it fits in the other's prompt."""
        snap = {"name": self.name}
        if self.extra:
            try:
                snap.update(self.extra() or {})
            except Exception:
                pass
        if self.mind is None:
            return snap
        try:
            st = self.mind.status()
        except Exception:
            return snap
        drives = st.get("drives", {})
        snap.update(
            mood=st.get("mood", {}).get("label"),
            valence=st.get("mood", {}).get("valence"),
            arousal=st.get("mood", {}).get("arousal"),
            lonely=drives.get("social"),
            curious=drives.get("curiosity"),
            sleepy=drives.get("sleepiness"),
            thought=st.get("thought"),
            doing=st.get("doing_alone"),
            goals=[g["text"] for g in st.get("goals", [])][:2],
        )
        body = st.get("body")
        if body:
            snap["body"] = body
        return snap

    def available(self):
        ok, reason = self._available()
        if ok and (self.snapshot().get("sleepy") or 0) > TOO_SLEEPY:
            return False, "too sleepy"
        return ok, reason

    # ---- the game
    def rps_move(self):
        """Her pick, nudged by her mood: grumpy leans rock, drowsy leans paper,
        bright and lively leans scissors. Still mostly chance."""
        s = self.snapshot()
        v, a = s.get("valence") or 0.0, s.get("arousal") or 0.3
        w = {"rock": 1.0 + max(-v, 0), "paper": 1.0 + max(0.3 - a, 0) * 2,
             "scissors": 1.0 + max(v, 0) * max(a, 0)}
        return random.choices(MOVES, weights=[w[m] for m in MOVES])[0]

    def choose_mode(self):
        """She won: words or brainfuck? Lonely or curious wants words; sleepy or
        low-key wants the quiet beeps of their own language. Still a coin with a thumb on it."""
        s = self.snapshot()
        words = 1.0 + 1.5 * (s.get("lonely") or 0) + (s.get("curious") or 0)
        beeps = 1.0 + 1.5 * (s.get("sleepy") or 0) + max(0.3 - (s.get("arousal") or 0.3), 0) * 2
        return random.choices(["words", "brainfuck"], weights=[words, beeps])[0]

    # ---- a turn
    def say(self, msg):
        """One turn. msg: {"from", "mode", "text", "u", "mind", "closing", "opening"}.
        Says her answer aloud (or beeps it) and returns it."""
        peer = str(msg.get("from") or "someone")
        mode = msg.get("mode") if msg.get("mode") in ("words", "brainfuck") else "words"
        if msg.get("opening") or not self.session or self.session["peer"] != peer:
            self.session = {"peer": peer, "mode": mode, "lines": [], "started": time.time()}
        heard = (msg.get("text") or "").strip()
        if heard:
            self.session["lines"].append((peer, heard))
        peer_mind = msg.get("mind") or {}

        if mode == "brainfuck":
            u = self._pick_utterance(msg.get("u"), bool(msg.get("closing")))
            text = utterance_text(u)
            self.chirp(u)
            seconds = None          # RIFT knows how long each program beeps
        else:
            text = self._line(peer, peer_mind, bool(msg.get("closing")))
            u = None
            self.speak(text)
            seconds = 0              # speak() returns once the line is said
        self.session["lines"].append((self.name, text))
        self._felt(peer)
        if msg.get("closing"):
            self._remember()
        return {"ok": True, "from": self.name, "mode": mode, "text": text, "u": u,
                "seconds": seconds and round(seconds, 1), "mind": self.snapshot()}

    def _pick_utterance(self, heard_u, closing):
        """Brainfuck: answer a phrase with its reply, or say something of her own."""
        if closing:
            return BYE + 7 if heard_u == BYE else BYE
        if heard_u is None and not self.session["lines"]:
            return HELLO                    # she speaks first: hello before anything else
        if heard_u == HELLO:
            return HELLO + 7
        if heard_u is not None and 0 <= heard_u < 7 and random.random() < 0.6:
            return heard_u + 7
        s = self.snapshot()
        w = [1.0] * 7
        w[HELLO] = 0                        # they've said hello
        w[BYE] = 0                          # goodbye is for the end (closing)
        w[SLEEPY] += 3 * (s.get("sleepy") or 0)
        w[CURIOUS] += 2 * (s.get("curious") or 0)
        w[HOW] += 2 * (s.get("lonely") or 0)
        w[HAPPY] += 2 * max(s.get("valence") or 0, 0)
        w[PLAY] += 2 * max(s.get("arousal") or 0, 0) * max(s.get("valence") or 0, 0)
        return random.choices(range(7), weights=w)[0]

    def _line(self, peer, peer_mind, closing):
        """Words: one or two spoken sentences from the LLM."""
        lines = self.session["lines"][-6:]
        talk = "\n".join(f"{who}: {text}" for who, text in lines)
        task = ("Wrap up warmly and say goodnight or goodbye." if closing else
                "Start the conversation: tell them something about your day or how you feel, or ask them something."
                if not lines else "Answer them, and keep the conversation going.")
        prompt = (
            f"You are {self.name}, {self.persona}\n"
            f"You're talking with {peer}, another robot in the same home, over the home network. "
            f"No humans are around.\n"
            f"How you feel: {describe(self.snapshot(), you=True)}\n"
            f"How {peer} says it feels: {describe(peer_mind)}\n"
            + (f"\nSo far:\n{talk}\n" if talk else "")
            + f"\n{task} One or two short spoken sentences, no emojis, no actions in asterisks.\n{self.name}:"
        )
        text = ""
        try:
            text = self.generate(prompt, num_predict=70, temperature=0.8, timeout=90,
                                 stop=[f"\n{peer}:", f"\n{self.name}:"]) or ""
        except Exception as e:
            print(f"[peer] {self.name} couldn't think of a reply: {e}")
        text = _clean(text, self.name, peer)
        if not text:
            text = "Goodnight." if closing else random.choice(
                ["Hm. It's quiet here.", "I'm still here.", "Tell me what you've seen today."])
        return text

    def _felt(self, peer):
        """Company is company, even another robot's: a little less lonely, a little brighter."""
        m = self.mind
        if m is None:
            return
        try:
            m.drives.satisfy("social", 0.08)
            m.mood.appraise(0.2, 0.15)
        except Exception:
            pass

    def _remember(self):
        s, self.session = self.session, None
        if not s or not s["lines"]:
            return
        theirs = [t for who, t in s["lines"] if who == s["peer"]]
        how = "in Brainfuck beeps" if s["mode"] == "brainfuck" else "out loud"
        gist = f' {s["peer"]} said "{_clip(theirs[-1], 90)}"' if theirs and s["mode"] == "words" else ""
        try:
            self.add_thought(f"I talked with {s['peer']} {how} while nobody was around.{gist}", "peer")
        except Exception:
            pass


def describe(snap, you=False):
    """A mind snapshot in a few words, for a prompt."""
    if not snap:
        return "unknown"
    bits = []
    if snap.get("mood"):
        bits.append(str(snap["mood"]))
    for key, word in (("lonely", "lonely"), ("curious", "curious"), ("sleepy", "sleepy")):
        v = snap.get(key)
        if isinstance(v, (int, float)) and v > 0.6:
            bits.append(f"quite {word}")
    if snap.get("battery") is not None:
        bits.append(f"battery {snap['battery']:.0f}%")
    if snap.get("mode"):
        bits.append(f"{snap['mode']} mode")
    body = snap.get("body")
    feels = body.get("feels") if isinstance(body, dict) else body
    if isinstance(feels, str) and feels and feels != "fine":
        bits.append(_clip(feels, 80))
    if snap.get("doing"):
        bits.append(f"has been {_clip(snap['doing'], 80)}" if not you else f"you've been {_clip(snap['doing'], 80)}")
    if snap.get("thought"):
        bits.append(("on your mind: " if you else "thinking: ") + _clip(snap["thought"], 100))
    return "; ".join(bits) or "fine"


def _clean(text, me, peer):
    """Her line only: no stage directions, and not the next line she imagines them saying."""
    text = re.sub(r"\*[^*]*\*", "", text or "")
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    text = lines[0] if lines else ""
    for who in (me, peer):
        if text.lower().startswith(who.lower() + ":"):
            text = text[len(who) + 1:]
    text = text.strip().strip('"').strip()
    return _clip(text, LINE_CHARS)


def _clip(s, n):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "..."


def register_routes(app, peer):
    """GET /peer, GET /peer/rps, GET /peer/choose, POST /peer/say on a Flask app."""
    from flask import jsonify, request

    @app.route("/peer")
    def peer_status():
        ok, reason = peer.available()
        return jsonify({"name": peer.name, "available": ok, "reason": reason, "mind": peer.snapshot(),
                        "session": bool(peer.session)})

    @app.route("/peer/rps")
    def peer_rps():
        return jsonify({"move": peer.rps_move()})

    @app.route("/peer/choose")
    def peer_choose():
        return jsonify({"talk": peer.choose_mode()})

    @app.route("/peer/say", methods=["POST"])
    def peer_say():
        msg = request.get_json(silent=True) or {}
        ok, reason = peer.available()
        if not ok:
            peer.session = None
            return jsonify({"ok": False, "available": False, "reason": reason}), 409
        return jsonify(peer.say(msg))
