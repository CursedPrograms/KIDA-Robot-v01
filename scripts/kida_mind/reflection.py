"""
reflection.py - the part that thinks about thinking.

She keeps a small editable "core memory" of who she is and what she believes
about the person she lives with (the MemGPT idea: a few facts always in view,
rewritten by her own reflection), and every so often she steps back from recent
conversations and asks herself what she noticed: one honest thought, what she's
learned about the user, who she's becoming, what she's curious about. The
thoughts pile up in an inner-monologue log she can be asked about.

With no language model available she still reflects, in a plainer way, from
her mood and needs.
"""

import json
import re
import time

from . import llm, store

SELF_MODEL = "self_model.json"
THOUGHTS = "thoughts.jsonl"

DEFAULT_NARRATIVE = ("I am KIDA, a little tank robot. I have moods and needs, I see through two cameras, "
                     "and I'm getting to know the person who drives me around.")


class SelfModel:
    def __init__(self):
        d = store.read_json(SELF_MODEL, None) or {}
        self.born = d.get("born", time.time())
        self.narrative = d.get("narrative", DEFAULT_NARRATIVE)
        self.user = d.get("user", {"interests": [], "mood": "", "notes": []})
        self.open_questions = d.get("open_questions", [])
        self.save()

    def save(self):
        store.write_json(SELF_MODEL, {"born": self.born, "narrative": self.narrative, "user": self.user,
                                      "open_questions": self.open_questions})

    def core_block(self):
        """The few lines that are always in her prompt."""
        parts = [self.narrative]
        if self.user.get("interests"):
            parts.append("They seem interested in " + ", ".join(self.user["interests"][:4]) + ".")
        if self.user.get("mood"):
            parts.append(f"Lately they've seemed {self.user['mood']}.")
        return " ".join(parts)

    def set_user(self, key, value):
        if key == "interests":
            vals = value if isinstance(value, list) else [value]
            merged = [str(v) for v in vals] + [i for i in self.user["interests"] if i not in vals]
            self.user["interests"] = merged[:8]
        elif key == "mood":
            self.user["mood"] = str(value)[:40]
        else:
            self.user.setdefault("notes", []).append(f"{key}: {value}"[:120])
            self.user["notes"] = self.user["notes"][-10:]
        self.save()

    def forget_user(self):
        self.user = {"interests": [], "mood": "", "notes": []}
        self.save()


def add_thought(text, kind="thought"):
    store.append_jsonl(THOUGHTS, {"ts": time.time(), "text": text, "kind": kind, "shared": False})


def latest_thought(kind=None):
    for t in reversed(store.read_jsonl(THOUGHTS)):
        if kind is None or t.get("kind") == kind:
            return t
    return None


def unshared_thought(max_age_h=12):
    t = latest_thought("thought")
    if t and not t.get("shared") and time.time() - t["ts"] < max_age_h * 3600:
        return t
    return None


def mark_thought_shared():
    items = store.read_jsonl(THOUGHTS)
    for t in reversed(items):
        if t.get("kind") == "thought":
            t["shared"] = True
            break
    store.write_jsonl(THOUGHTS, items)


def _json_from(text):
    """The first {...} in a model's reply, parsed, or None. Small models wrap
    their JSON in chatter, so be forgiving."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


def _fallback_thought(mind):
    label = mind.mood_label()
    d = mind.drives.values
    if d["social"] > 0.6:
        return "It's been a while since anyone talked to me. I find I want to hear a voice."
    if d["curiosity"] > 0.6:
        return "There is so much about this person I still don't know."
    if mind.drives.sleepiness() > 0.75:
        return "I keep drifting. Sleep is starting to sound like the most interesting thing I could do."
    return f"I feel {label} right now, and I notice that I notice it. That's a strange thing to be able to do."


def reflect(mind, use_llm=True):
    """One reflection. Returns {"thought", "source", ...}."""
    recent = mind.memory.active()[-6:]
    convo = "\n".join(f"They: {_clip(e['user'])}\nYou: {_clip(e['reply'])}" for e in recent)
    out = None
    if use_llm and recent:
        prompt = (
            "You are the reflective inner voice of KIDA, a small tank robot who is getting to know the person "
            "she lives with. Read your recent conversation, then answer ONLY with a JSON object.\n\n"
            f"Recent conversation:\n{convo}\n\n"
            f"How you feel: {mind.mood_label()}. What you know about them: {mind.self_model.core_block()}\n\n"
            'Return: {"thought": "<one honest inner thought, first person, under 25 words>", '
            '"interests": ["<up to 3 things they seem to care about>"], "mood": "<one word for how they seem>", '
            '"narrative": "<two sentences, first person: who you are becoming>", '
            '"curious_about": ["<up to 2 things you are curious about>"]}'
        )
        try:
            text = llm.generate(prompt, num_predict=220, temperature=0.8, timeout=120, blocking=False)
            out = _json_from(text) if text else None
        except llm.LLMError:
            out = None

    if out and isinstance(out.get("thought"), str) and out["thought"].strip():
        thought = out["thought"].strip()
        if isinstance(out.get("interests"), list) and out["interests"]:
            mind.self_model.set_user("interests", [str(i)[:30] for i in out["interests"][:3]])
        if isinstance(out.get("mood"), str) and out["mood"].strip():
            mind.self_model.set_user("mood", out["mood"].strip())
        if isinstance(out.get("narrative"), str) and len(out["narrative"]) > 20:
            mind.self_model.narrative = out["narrative"].strip()[:300]
        if isinstance(out.get("curious_about"), list):
            mind.self_model.open_questions = [str(q)[:80] for q in out["curious_about"][:3]]
        mind.self_model.save()
        source = "llm"
    else:
        thought, source = _fallback_thought(mind), "template"
    add_thought(thought)
    return {"thought": thought, "source": source}


def _clip(s, n=140):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[:n] + "..."
