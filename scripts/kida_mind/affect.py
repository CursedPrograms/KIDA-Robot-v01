"""
affect.py - mood.

Two numbers, as in the psychology of emotion: valence (unpleasant..pleasant,
-1..1) and arousal (calm..activated, 0..1). Events push them; time pulls them
back to a baseline, so a good conversation warms her for a while and then it
fades - like a mood, not like a switch.
"""

import math
import random
import re
import time

POSITIVE = {
    "love", "loved", "great", "awesome", "thanks", "thank", "good", "nice", "happy", "amazing", "wonderful",
    "cool", "beautiful", "fun", "best", "like", "glad", "excellent", "perfect", "haha", "lol", "brilliant",
    "fantastic", "sweet", "cute", "funny", "yes", "please", "welcome", "hello", "hi", "hey", "smart",
}
NEGATIVE = {
    "hate", "hated", "bad", "stupid", "annoying", "sad", "angry", "terrible", "awful", "shut", "stop", "worst",
    "boring", "ugly", "dumb", "useless", "lonely", "scared", "hurt", "die", "wrong", "broken", "sucks", "idiot",
    "shutup", "go", "away", "never", "tired", "worried",
}
NEGATORS = {"not", "no", "never", "don't", "dont", "isn't", "isnt", "can't", "cant", "won't", "wont"}

BASE_VALENCE = 0.15
BASE_AROUSAL = 0.3
VALENCE_HALF_LIFE_S = 30 * 60
AROUSAL_HALF_LIFE_S = 15 * 60


def sentiment(text):
    """(valence -1..1, intensity 0..1) of what someone said. A crude lexicon -
    good enough to tell warmth from hostility."""
    words = re.findall(r"[a-z']+", text.lower())
    score = 0.0
    for i, w in enumerate(words):
        s = 1.0 if w in POSITIVE else -1.0 if w in NEGATIVE else 0.0
        if s and i > 0 and words[i - 1] in NEGATORS:
            s = -s * 0.7
        score += s
    exclaim = min(text.count("!"), 3) * 0.1
    shout = 0.15 if len(text) > 6 and text.isupper() else 0.0
    valence = max(-1.0, min(1.0, score / 3.0))
    intensity = max(0.0, min(1.0, abs(score) / 3.0 + exclaim + shout))
    return valence, intensity


TEMPER_PULL_PER_H = 0.15    # a good or bad day slowly wears off...
TEMPER_NOISE_PER_SQRT_H = 0.06  # ...while chance keeps nudging it
TEMPER_LIMIT = 0.3


PERSONAL = re.compile(
    r"\b(my (mom|mum|mother|dad|father|grandfather|grandmother|grandma|grandpa|brother|sister|wife|husband|partner|"
    r"girlfriend|boyfriend|son|daughter|kids?|children|family|friend|best friend|dog|cat|childhood|late)|"
    r"passed away|died|funeral|wedding|born|grew up|growing up|years ago|first time|remember when|taught me|"
    r"miss (him|her|them|you)|i love|i lost|diagnosed|divorce|moved (here|to)|graduat\w+|promotion|fired)\b", re.I)


def disclosure(text):
    """How personal / significant what someone said is (0..0.6), independent of
    emotional *words*: telling her about your grandfather matters even in a flat
    voice, and a long, story-like message carries more than a quick command."""
    score = 0.0
    hits = len(PERSONAL.findall(text))
    if hits:
        score += min(0.45, 0.25 + 0.1 * (hits - 1))
    if len(text.split()) >= 15:
        score += 0.1
    return min(0.6, score)


# Warmth, not romance: kind words about her, fondness, missing her. It lifts her
# mood and eases loneliness - there is no desire drive in KIDA's mind.
AFFECTION = re.compile(
    r"\b(you'?re (so |really |very )?(cute|lovely|adorable|awesome|amazing|the best|a good robot|smart|clever)|"
    r"i love you|love you|i like you|i missed you|miss(ed)? you|hugs?|good (girl|robot|job)|well done|"
    r"proud of you|thank you so much|you'?re my (friend|buddy|favou?rite))\b", re.I)


def affection(text):
    """How warm / fond what someone said is toward her (0..1)."""
    hits = len(AFFECTION.findall(text))
    return min(1.0, 0.45 + 0.2 * (hits - 1)) if hits else 0.0


class Mood:
    """Valence and arousal, plus a slow-moving temperament: today's good-day /
    bad-day offset. Chance is part of the model on purpose - the same event
    doesn't move her exactly the same way twice, and she has days."""

    def __init__(self, valence=BASE_VALENCE, arousal=BASE_AROUSAL, ts=None, temper=None):
        self.valence = valence
        self.arousal = arousal
        self.ts = ts or time.time()
        self.temper = random.gauss(0.0, 0.1) if temper is None else temper  # today's temperament

    @property
    def baseline_valence(self):
        return BASE_VALENCE + self.temper

    def decay(self, now=None):
        now = now or time.time()
        dt = max(0.0, now - self.ts)
        self.ts = now
        dt_h = min(dt / 3600.0, 48.0)
        # temperament: an Ornstein-Uhlenbeck walk - pulled toward neutral, shaken by noise
        self.temper += -self.temper * TEMPER_PULL_PER_H * dt_h + random.gauss(0.0, TEMPER_NOISE_PER_SQRT_H * math.sqrt(dt_h))
        self.temper = max(-TEMPER_LIMIT, min(TEMPER_LIMIT, self.temper))
        base_v = self.baseline_valence
        self.valence = base_v + (self.valence - base_v) * math.pow(0.5, dt / VALENCE_HALF_LIFE_S)
        self.arousal = BASE_AROUSAL + (self.arousal - BASE_AROUSAL) * math.pow(0.5, dt / AROUSAL_HALF_LIFE_S)
        self.valence = max(-1.0, min(1.0, self.valence + random.gauss(0.0, 0.01)))  # the small tremor of being alive

    def appraise(self, valence, intensity=0.5):
        """Something happened: `valence` says how good/bad, `intensity` how strongly."""
        intensity *= random.uniform(0.75, 1.25)
        self.valence = max(-1.0, min(1.0, self.valence + valence * intensity * 0.4))
        self.arousal = max(0.0, min(1.0, self.arousal + intensity * 0.25))

    def label(self, drives=None, hour=12.0):
        """One word for how she feels. Needs colour the mood: a lonely, sleepy or
        jumpy KIDA says so."""
        v, a = self.valence, self.arousal
        if drives is not None:
            if drives.sleepiness(hour) > 0.75:
                return "sleepy"
            if drives.values["security"] > 0.6:
                return "on edge"
            if drives.values["social"] > 0.75 and v < 0.5:
                return "lonely"
        if v > 0.45:
            return "excited" if a > 0.5 else "content"
        if v > 0.15:
            return "pleasant" if a > 0.35 else "calm"
        if v > -0.15:
            return "neutral" if a > 0.25 else "calm"
        if v > -0.45:
            return "down" if a < 0.5 else "irritated"
        return "upset"

    def to_dict(self):
        return {"valence": round(self.valence, 3), "arousal": round(self.arousal, 3), "ts": self.ts,
                "temper": round(self.temper, 3)}

    @classmethod
    def from_dict(cls, d):
        d = d or {}
        return cls(d.get("valence", BASE_VALENCE), d.get("arousal", BASE_AROUSAL), d.get("ts"), d.get("temper"))
