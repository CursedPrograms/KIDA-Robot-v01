"""
opinions.py - views that change.

She holds a stance (-1 dislike .. +1 like) and a confidence on a handful of
topics. What people say, and how they feel about it, moves the stance a little;
confidence grows with evidence; and small random drift means her tastes wander
over weeks instead of staying fixed. Every change is written down, so she can
say "I used to think that, but I've changed my mind".

She starts with the opinions her persona implies (she loves technology). She is
allowed to disagree with you.
"""

import random
import time

from . import store
from .affect import sentiment

FILE = "opinions.json"

TOPICS = {
    "technology": ["computer", "technology", "tech", "software", "robot", "code", "coding", "gadget", "program"],
    "music": ["music", "song", "songs", "guitar", "band", "album", "playlist", "concert", "sing", "piano"],
    "night": ["night", "midnight", "dark", "stars", "moon", "late"],
    "sleep": ["sleep", "nap", "dream", "dreams", "bed", "tired", "rest"],
    "nature": ["nature", "forest", "outside", "rain", "ocean", "mountain", "garden", "walk", "hike"],
    "art": ["art", "painting", "draw", "drawing", "film", "movie", "poem", "poetry", "book", "story"],
    "privacy": ["privacy", "private", "surveillance", "camera", "tracking", "watching"],
    "artificial minds": ["conscious", "consciousness", "sentient", "alive", "ai", "soul", "feelings", "aware"],
    "people": ["friend", "friends", "family", "people", "company", "together", "lonely", "alone"],
    "driving": ["drive", "driving", "speed", "fast", "race", "racing", "tank", "wheels", "treads", "zoom"],
}

# What her persona (a sarcastic little tank robot who loves technology and going fast) starts out believing.
INITIAL = {
    "technology": (0.75, 0.6), "music": (0.4, 0.2), "night": (0.35, 0.3), "sleep": (0.3, 0.3),
    "nature": (0.25, 0.15), "art": (0.4, 0.2), "privacy": (0.15, 0.25),
    "artificial minds": (0.0, 0.1), "people": (0.4, 0.3), "driving": (0.6, 0.4),
}

LEARNING_RATE = 0.18
DRIFT_PER_DAY = 0.03


def _describe_stance(stance, confidence):
    """For summaries: "strongly likes" / "is undecided" / "hasn't formed a view"."""
    if confidence < 0.2:
        return "hasn't formed a view"
    strength = "strongly" if abs(stance) > 0.6 else "somewhat" if abs(stance) > 0.25 else "mildly"
    if abs(stance) < 0.12:
        return "is undecided"
    return f"{strength} {'likes' if stance > 0 else 'dislikes'}"


def _sentence(topic, o):
    """A second-person sentence for her own prompt."""
    if o["confidence"] < 0.2:
        return f"You haven't formed a view on {topic} yet."
    if abs(o["stance"]) < 0.12:
        return f"You're undecided about {topic}."
    strength = "strongly" if abs(o["stance"]) > 0.6 else "somewhat" if abs(o["stance"]) > 0.25 else "mildly"
    return f"You {strength} {'like' if o['stance'] > 0 else 'dislike'} {topic}."


class Opinions:
    def __init__(self):
        data = store.read_json(FILE, None)
        if not data:
            data = {
                "stances": {t: {"stance": s, "confidence": c, "n": 0, "changed": None}
                            for t, (s, c) in INITIAL.items()},
                "history": [], "drift_ts": time.time(),
            }
        self.data = data
        for t, (s, c) in INITIAL.items():   # topics added in a later version
            self.data["stances"].setdefault(t, {"stance": s, "confidence": c, "n": 0, "changed": None})

    def save(self):
        store.write_json(FILE, self.data)

    def topics_in(self, text):
        words = set(text.lower().replace("?", " ").replace(",", " ").replace(".", " ").split())
        return [t for t, kw in TOPICS.items() if words & set(kw)]

    def learn_from(self, text, now=None):
        """The user said something about a topic (and felt some way about it):
        move her stance toward that feeling. Returns the topics it touched."""
        now = now or time.time()
        touched = self.topics_in(text)
        if not touched:
            return []
        valence, intensity = sentiment(text)
        if intensity < 0.15:      # a neutral mention isn't evidence for anything
            return touched
        for t in touched:
            o = self.data["stances"][t]
            # people persuade her less when she's already sure, and she doesn't just
            # mirror them: she moves only part of the way.
            rate = LEARNING_RATE * (1.0 - 0.5 * o["confidence"]) * random.uniform(0.7, 1.3)
            new = max(-1.0, min(1.0, o["stance"] + rate * (valence * 0.9 - o["stance"])))
            if abs(new - o["stance"]) >= 0.08 or o["stance"] * new < 0:   # a real change of view, not a wobble
                self._record_change(t, o["stance"], new, now, f"after you said: {text[:60]!r}")
            o["stance"] = round(new, 3)
            o["confidence"] = round(min(0.95, o["confidence"] + 0.05), 3)
            o["n"] += 1
            o["changed"] = now
        self.save()
        return touched

    def reflect(self, topic, delta, reason, now=None):
        """A reflection changed her mind (or firmed it up)."""
        if topic not in self.data["stances"]:
            return
        o = self.data["stances"][topic]
        new = max(-1.0, min(1.0, o["stance"] + max(-0.3, min(0.3, delta))))
        self._record_change(topic, o["stance"], new, now or time.time(), reason)
        o["stance"] = round(new, 3)
        o["confidence"] = round(min(0.95, o["confidence"] + 0.03), 3)
        self.save()

    def _record_change(self, topic, old, new, now, reason):
        if abs(new - old) < 0.04:
            return
        self.data["history"].append({"ts": now, "topic": topic, "from": round(old, 2), "to": round(new, 2), "why": reason})
        self.data["history"] = self.data["history"][-100:]

    def drift(self, now=None):
        """Tastes wander: a small random walk, so she isn't the same about everything forever."""
        now = now or time.time()
        days = min(30.0, (now - self.data.get("drift_ts", now)) / 86400.0)
        self.data["drift_ts"] = now
        if days <= 0:
            return
        for o in self.data["stances"].values():
            step = random.gauss(0.0, DRIFT_PER_DAY * days ** 0.5) * (1.0 - 0.6 * o["confidence"])
            o["stance"] = round(max(-1.0, min(1.0, o["stance"] + step)), 3)
        self.save()

    def view_on(self, text, limit=2):
        """Sentences about her views on what `text` touches on, for her prompt."""
        lines = []
        for t in self.topics_in(text)[:limit]:
            o = self.data["stances"][t]
            lines.append(_sentence(t, o))
            recent = [h for h in self.data["history"] if h["topic"] == t]
            if recent and time.time() - recent[-1]["ts"] < 30 * 86400:
                r = recent[-1]
                lines.append(f"You used to feel {'more positive' if r['from'] > r['to'] else 'more negative'} about {t}; "
                             f"you've changed your mind ({r['why']}).")
        return " ".join(lines)

    def strongest(self, n=3):
        ranked = sorted(self.data["stances"].items(), key=lambda kv: -abs(kv[1]["stance"]) * kv[1]["confidence"])
        return [(t, o) for t, o in ranked[:n] if o["confidence"] >= 0.2]

    def summary(self):
        parts = [f"{t}: {_describe_stance(o['stance'], o['confidence'])}" for t, o in self.strongest(4)]
        return "; ".join(parts)
