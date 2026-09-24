"""
memory.py - episodic memory as a graph: the shared history.

Every exchange becomes an episode (a node). Episodes are linked - to what came
right before ("then"), to memories about similar things ("similar"), and to
ones that share topics ("topic"). Recall starts from what a cue is directly
about, then lets activation spread along the links, so she can reach the quiet
conversation from three months ago because it's connected to something you said
today. Recall is mood-congruent (a low mood surfaces sadder memories), and every
recall strengthens the memory - the testing effect.

Memories also fade. Strength decays with time (emotional ones more slowly) and
sleep replays and strengthens the important ones; what falls away is archived,
not deleted, and old archived episodes are folded into short "gists".
"""

import math
import random
import time
import uuid

from . import store
from .vectors import VectorIndex, embed, tokens

EPISODES = "episodes.jsonl"
GISTS = "gists.jsonl"

ARCHIVE_BELOW = 0.08
BASE_HALF_LIFE_H = 24.0 * 14     # a plain memory halves in strength every two weeks...
EMOTION_HALF_LIFE_BONUS = 6.0    # ...an intensely emotional one lasts up to 7x longer (months)
FACT_HALF_LIFE_BONUS = 2.0       # ...and one where she learned something about you, longer still
GIST_AFTER_DAYS = 14


def _recency(ts, now):
    return math.exp(-max(0.0, now - ts) / 3600.0 / 72.0)


class Memory:
    def __init__(self):
        self.episodes = []   # every episode, oldest first (archived ones included)
        self.gists = []
        self.index = VectorIndex()
        self._by_id = {}
        self.load()

    # ---------------------------------------------------------------- storage
    def load(self):
        self.episodes = store.read_jsonl(EPISODES)
        self.gists = store.read_jsonl(GISTS)
        self.index = VectorIndex()
        self._by_id = {e["id"]: e for e in self.episodes}
        for e in self.episodes:
            if not e.get("archived"):
                self.index.add(e["id"], self._text(e))

    def save(self):
        store.write_jsonl(EPISODES, self.episodes)
        store.write_jsonl(GISTS, self.gists)

    @staticmethod
    def _text(e):
        return f"{e.get('user', '')} {e.get('reply', '')}"

    def active(self):
        return [e for e in self.episodes if not e.get("archived")]

    def count(self):
        return len(self.active())

    # ------------------------------------------------------------- adding
    def add_episode(self, user, reply, valence=0.0, intensity=0.0, facts=(), voice=None, now=None):
        now = now or time.time()
        tags = sorted(set(tokens(user)) | set(tokens(reply)))[:24]
        # salience: how much this is worth keeping. Feeling, personal facts and
        # things unlike what she already knows all raise it.
        novelty = 1.0
        hits = self.index.search(f"{user} {reply}", k=1)
        if hits:
            novelty = max(0.0, 1.0 - hits[0][1])
        salience = min(1.0, 0.2 + 0.45 * intensity + 0.3 * (1 if facts else 0) + 0.25 * novelty)
        ep = {
            "id": uuid.uuid4().hex[:10], "ts": now, "user": user, "reply": reply, "tags": tags,
            "valence": round(valence, 3), "intensity": round(intensity, 3), "salience": round(salience, 3),
            "strength": round(salience, 3), "strength_ts": now, "recalls": 0, "last_recall": None,
            "facts": list(facts), "links": [], "archived": False,
        }
        if voice:
            ep["voice"] = voice
        self._link(ep)
        self.episodes.append(ep)
        self._by_id[ep["id"]] = ep
        self.index.add(ep["id"], self._text(ep))
        self.save()
        return ep

    def _link(self, ep):
        """Connect a new episode to the past."""
        active = self.active()
        if active:
            prev = active[-1]
            if ep["ts"] - prev["ts"] < 30 * 60:
                self._connect(ep, prev, 0.35, "then")
        vec = embed(self._text(ep))
        for other_id, score in self.index.search(vec, k=4, min_score=0.14):
            other = self._by_id.get(other_id)
            if other is not None and other is not ep:
                self._connect(ep, other, round(score, 3), "similar")

        # Topic links: memories that share a *distinctive* word - one that's rare
        # across everything she remembers - are about the same thing, even when
        # the rest of the sentence isn't ("grandfather" ties two months apart).
        n = max(1, len(active))
        doc_freq = {}
        for other in active:
            for t in other["tags"]:
                doc_freq[t] = doc_freq.get(t, 0) + 1
        rare = {t for t in ep["tags"] if doc_freq.get(t, 0) <= max(3, int(0.05 * n))}
        for other in active:
            shared = rare & set(other["tags"])
            if shared and not any(l["to"] == other["id"] for l in ep["links"]):
                self._connect(ep, other, round(min(0.6, 0.25 * len(shared) + 0.1), 3), "topic")

    @staticmethod
    def _connect(a, b, weight, kind):
        if any(l["to"] == b["id"] for l in a["links"]):
            return
        a["links"].append({"to": b["id"], "w": weight, "kind": kind})
        if not any(l["to"] == a["id"] for l in b["links"]):
            b["links"].append({"to": a["id"], "w": weight, "kind": kind})

    # ------------------------------------------------------------- recall
    def recall(self, cue, k=3, mood_valence=None, now=None, min_score=0.18):
        """Memories a cue brings to mind: [(episode, score, "direct"|"association")]."""
        now = now or time.time()
        if not cue.strip() or not self.index.ids:
            return []
        activation = {}
        via = {}
        seeds = self.index.search(cue, k=6, min_score=0.15)
        for ep_id, sim in seeds:
            activation[ep_id] = sim
            via[ep_id] = "direct"
        for ep_id, sim in seeds:   # spread one hop along the links
            for link in self._by_id[ep_id]["links"]:
                other = self._by_id.get(link["to"])
                if other is None or other.get("archived"):
                    continue
                spread = sim * link["w"] * 0.6
                if spread > activation.get(other["id"], 0.0):
                    activation[other["id"]] = spread
                    via.setdefault(other["id"], "association")

        scored = []
        for ep_id, act in activation.items():
            e = self._by_id[ep_id]
            s = 0.55 * act + 0.2 * e["strength"] + 0.1 * _recency(e["ts"], now)
            if mood_valence is not None:   # mood-congruent recall
                s += 0.15 * max(0.0, 1.0 - abs(e["valence"] - mood_valence))
            scored.append((e, s, via[ep_id]))
        scored = [t for t in scored if t[1] >= min_score]
        scored.sort(key=lambda t: -t[1])
        return scored[:k]

    def mark_recalled(self, episodes, now=None):
        now = now or time.time()
        for e in episodes:
            e["recalls"] += 1
            e["last_recall"] = now
            e["strength"] = round(min(1.0, e["strength"] + 0.1), 3)
            e["strength_ts"] = now
        if episodes:
            self.save()

    # ------------------------------------------------------- consolidation
    def consolidate(self, now=None):
        """The slow-wave part of sleep: replay the important, let the rest fade,
        archive what's gone, fold old archives into gists."""
        now = now or time.time()
        stats = {"replayed": 0, "strengthened": 0, "faded": 0, "archived": 0, "gists": 0}
        active = self.active()
        for e in active:
            age_h = max(0.0, (now - e["strength_ts"]) / 3600.0)
            half_life = BASE_HALF_LIFE_H * (1.0 + EMOTION_HALF_LIFE_BONUS * e["intensity"]
                                            + (FACT_HALF_LIFE_BONUS if e["facts"] else 0.0))
            if e["recalls"]:
                half_life *= 1.0 + 0.5 * min(e["recalls"], 6)   # rehearsed memories last
            before = e["strength"]
            e["strength"] = round(e["strength"] * math.pow(0.5, age_h / half_life), 4)
            e["strength_ts"] = now
            if e["strength"] < before - 1e-4:
                stats["faded"] += 1

        replay = sorted(active, key=lambda e: -(e["salience"] * (1 + e["intensity"])))[:5]
        for e in replay:   # replay strengthens
            e["strength"] = round(min(1.0, e["strength"] + 0.06 * (0.5 + e["intensity"])), 4)
            stats["replayed"] += 1
            stats["strengthened"] += 1

        for e in active:
            if e["strength"] < ARCHIVE_BELOW and not e["recalls"]:
                e["archived"] = True
                self.index.remove(e["id"])
                stats["archived"] += 1

        stats["gists"] = self._make_gists(now)
        self.save()
        return stats

    def _make_gists(self, now):
        cutoff = now - GIST_AFTER_DAYS * 86400
        old = [e for e in self.episodes if e.get("archived") and e["ts"] < cutoff and not e.get("gisted")]
        if len(old) < 3:
            return 0
        by_week = {}
        for e in old:
            by_week.setdefault(time.strftime("%Y-W%W", time.localtime(e["ts"])), []).append(e)
        made = 0
        for week, group in by_week.items():
            counts = {}
            for e in group:
                for t in e["tags"]:
                    counts[t] = counts.get(t, 0) + 1
            top = [t for t, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:4]]
            mean_v = sum(e["valence"] for e in group) / len(group)
            feel = "a warm" if mean_v > 0.15 else "a heavy" if mean_v < -0.15 else "an ordinary"
            self.gists.append({"week": week, "ts": now, "n": len(group), "tags": top,
                               "text": f"{feel} stretch of {len(group)} conversations, mostly about {', '.join(top) or 'small things'}."})
            for e in group:
                e["gisted"] = True
            made += 1
        return made

    # ------------------------------------------------------- the user, over time
    def user_baseline(self, days=30, now=None):
        """The user's usual mood: mean valence of what they said over `days`."""
        now = now or time.time()
        vals = [e["valence"] for e in self.episodes if now - e["ts"] < days * 86400]
        return (sum(vals) / len(vals)) if len(vals) >= 5 else None

    def mood_shift(self, now=None):
        """A noticeable change in how the user sounds lately vs. their usual, as
        (delta, "lighter"|"heavier") or None. The 'you seem different today' detector."""
        now = now or time.time()
        base = self.user_baseline(30, now)
        recent = [e["valence"] for e in self.active()[-3:] if now - e["ts"] < 24 * 3600]
        if base is None or len(recent) < 2:
            return None
        delta = sum(recent) / len(recent) - base
        if abs(delta) >= 0.3:
            return round(delta, 2), ("lighter" if delta > 0 else "heavier")
        return None

    def topics(self, n=5):
        counts = {}
        for e in self.active():
            for t in e["tags"]:
                counts[t] = counts.get(t, 0) + 1
        return [t for t, c in sorted(counts.items(), key=lambda kv: -kv[1])[:n] if c >= 2]

    # ------------------------------------------------------------ forgetting
    def forget_last(self):
        active = self.active()
        if not active:
            return None
        e = active[-1]
        self._drop(e)
        self.save()
        return e

    def forget_matching(self, phrase):
        """Delete every episode that mentions `phrase`. Returns how many."""
        p = phrase.lower().strip()
        doomed = [e for e in self.episodes if p and p in self._text(e).lower()]
        for e in doomed:
            self._drop(e)
        if doomed:
            self.save()
        return len(doomed)

    def forget_all(self):
        n = len(self.episodes)
        self.episodes, self.gists, self._by_id = [], [], {}
        self.index = VectorIndex()
        self.save()
        return n

    def _drop(self, e):
        self.episodes = [x for x in self.episodes if x["id"] != e["id"]]
        self._by_id.pop(e["id"], None)
        self.index.remove(e["id"])
        for x in self.episodes:   # and every link pointing at it
            x["links"] = [l for l in x["links"] if l["to"] != e["id"]]
