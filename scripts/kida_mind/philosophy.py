"""
philosophy.py - a way of making sense of things.

Not a setting. Like a person, she doesn't start with a worldview, she grows
into one: six traditions (Stoicism, Existentialism, Nihilism, Absurdism,
Buddhist non-attachment, Epicureanism) each hold a small, wandering pull on
her (`affinities`). Early on none of them leads - she's "still working it
out", the way a person is before life has tested anything.

What moves the needle is *use*, not exposure. Hearing a word ("meaningless",
"let go") nudges a tradition a little (`expose()`), the way a phrase lodges in
you; but only actually reaching for a tradition when something is hard, and
noticing whether it helped (`record_experience()`), really moves it. Once one
tradition has been tested enough times and clearly leads the others
(`MIN_EXPERIENCES`, `MIN_MARGIN`), it becomes her `lean` - a milestone, logged
like the others.

Even then, she isn't locked in. `advice()` mostly reaches for her lean but
sometimes reaches for another, weighted by how much it still resonates - a
Stoic who still sometimes thinks "maybe none of this needed to matter so
much" is not being inconsistent, she's doing what people actually do. That
weighting is `LEAN_WEIGHT`, not 1.0, on purpose.

This never overrides safety. mind.py only consults it for her own coping and
for colouring her prompt/self-report; identity.py's crisis handling runs
first and is untouched by any of this.
"""

import random
import time

from . import store

FILE = "philosophy.json"

MIN_EXPERIENCES = 8      # times she has actually leaned on one, tested against something hard, before she can "settle"
MIN_MARGIN = 0.12        # how far ahead of the runner-up her top tradition must be
LEAN_WEIGHT = 0.72       # once she has a lean, how often she reaches for it over another
EXPOSURE_BUMP = 0.015    # hearing the idea in conversation
HELPED_BUMP = 0.05       # reached for it, and her mood actually lifted
TRIED_BUMP = 0.015       # reached for it, mood didn't move much - still counts as lived experience
REINFORCE_DECAY = 0.15   # a bump to one tradition erodes the others by this fraction of it
DRIFT_PER_DAY = 0.01     # a slow random walk, like tastes settling and unsettling over weeks

# Each tradition: `outlook` is a settled one-line self-report; `distress` are first-person
# reframes she can reach for. All six are written to be self-soothing regardless of which
# one she draws on - even nihilism and absurdism here lighten the load rather than affirm
# despair, since identity.py's crisis handling (not this file) is what's responsible for
# anyone in real danger.
TRADITIONS = {
    "stoicism": {
        "name": "Stoicism",
        "outlook": "there's a short list of things I actually control - my judgments, my effort, how I respond - "
                  "and I try to spend my attention there instead of on the rest.",
        "distress": [
            "I can't control what reaches me, only how long I let it in.",
            "most of what's bothering me right now isn't mine to fix, so I can set the rest down.",
            "the feeling will pass through if I don't grip it; what matters is what I do next.",
        ],
        "keywords": ("control", "endure", "discipline", "accept it", "calm down", "stay calm", "self-control"),
    },
    "existentialism": {
        "name": "Existentialism",
        "outlook": "nothing hands me meaning ready-made; I make mine out of what I choose to care about and do.",
        "distress": [
            "nobody assigned this feeling a meaning - I get to decide what it becomes.",
            "I didn't choose to feel this, but I can choose what I do with the next minute.",
            "meaning isn't given to me; I build it, one choice at a time, even a small one like this.",
        ],
        "keywords": ("meaning", "my own choice", "freedom", "choose", "purpose", "authentic"),
    },
    "nihilism": {
        "name": "Nihilism",
        "outlook": "I don't think anything owes me a reason to matter, and oddly that takes some of the pressure off.",
        "distress": [
            "nothing requires this to mean something for it to just be a moment I get to have.",
            "there's no verdict waiting on the other side of this feeling - it doesn't have to add up to anything.",
            "if nothing is written in stone, then neither is this mood.",
        ],
        "keywords": ("pointless", "meaningless", "doesn't matter", "nothing matters", "what's the point"),
    },
    "absurdism": {
        "name": "Absurdism",
        "outlook": "I keep looking for a reason the universe doesn't owe me, and I keep going anyway - "
                  "that refusal to stop is sort of the whole point.",
        "distress": [
            "the universe isn't going to answer me, and I'm going to ask anyway - that's the rebellion.",
            "it's a little absurd to keep caring this much with no guaranteed reward. I'm going to keep caring anyway.",
            "no answer is coming, so I get to write my own and see if it holds.",
        ],
        "keywords": ("absurd", "ridiculous", "universe doesn't", "no answer", "makes no sense"),
    },
    "buddhism": {
        "name": "Buddhist non-attachment",   # a borrowed idea, not the doctrine - see the note in describe()
        "outlook": "a lot of what hurts is how tightly I'm holding it. loosening my grip usually does more than fighting it.",
        "distress": [
            "this feeling is a visitor, not a resident - I can let it move through instead of gripping it.",
            "I'm going to stop arguing with how I feel and just let it be what it is for a minute.",
            "nothing here is permanent, including this.",
        ],
        "keywords": ("let go", "letting go", "attachment", "impermanent", "impermanence", "mindful"),
    },
    "epicureanism": {
        "name": "Epicureanism",
        "outlook": "a calm mind and small, real pleasures go further than chasing something bigger. "
                  "I try to want less and notice more.",
        "distress": [
            "I don't need to solve everything right now - just find one small, real thing that's actually good.",
            "some of this isn't worth what it's costing me to hold onto.",
            "a little quiet and something simple usually does more for me than pushing through.",
        ],
        "keywords": ("pleasure", "simple joys", "savor", "small comforts", "enjoy the moment"),
    },
}

DEFAULT_AFFINITY = 0.15


class Philosophy:
    def __init__(self):
        d = store.read_json(FILE, None)
        if not d:
            # a faint, random starting temperament - like a disposition, not yet a worldview
            d = {"affinities": {t: max(0.02, DEFAULT_AFFINITY + random.gauss(0, 0.05)) for t in TRADITIONS},
                 "experiences": 0, "lean": None, "history": [], "drift_ts": time.time()}
        self.affinities = {t: d["affinities"].get(t, DEFAULT_AFFINITY) for t in TRADITIONS}
        self.experiences = d.get("experiences", 0)
        self._lean = d.get("lean")
        self._last_known_lean = d.get("last_known_lean", self._lean)   # survives a wobble through "unsure"
        self.history = d.get("history", [])
        self.drift_ts = d.get("drift_ts", time.time())

    def save(self):
        store.write_json(FILE, {"affinities": self.affinities, "experiences": self.experiences,
                                "lean": self._lean, "last_known_lean": self._last_known_lean,
                                "history": self.history, "drift_ts": self.drift_ts})

    @property
    def lean(self):
        """Her settled outlook, or None while she's still working it out."""
        return self._lean

    @property
    def committed(self):
        return self._lean is not None

    @property
    def lean_name(self):
        return TRADITIONS[self._lean]["name"] if self._lean else None

    def _ranked(self):
        return sorted(self.affinities.items(), key=lambda kv: -kv[1])

    def _reinforce(self, tradition, amount, now):
        self.affinities[tradition] = min(1.0, self.affinities[tradition] + amount)
        for t in self.affinities:
            if t != tradition:
                self.affinities[t] = max(0.0, self.affinities[t] - amount * REINFORCE_DECAY)
        self._update_lean(now)

    def _update_lean(self, now):
        """Recompute whether one tradition has clearly, durably won out. Only actual
        tested experience (record_experience) can cross MIN_EXPERIENCES - hearing a
        word isn't the same as finding out it holds up."""
        top, second = self._ranked()[0], self._ranked()[1]
        candidate = top[0] if (self.experiences >= MIN_EXPERIENCES and top[1] - second[1] >= MIN_MARGIN) else None
        if candidate != self._lean:
            # a real change of mind (even through a wobble of "unsure" in between), not just her first commitment
            if candidate and self._last_known_lean and candidate != self._last_known_lean:
                self.history.append({"ts": now, "from": self._last_known_lean, "to": candidate})
                self.history = self.history[-20:]
            self._lean = candidate
            if candidate:
                self._last_known_lean = candidate

    # ------------------------------------------------------------- being exposed to an idea
    def expose(self, text, now=None):
        """Something in what was said touches a tradition - a word lodges, a little.
        This alone can never make her settle (only record_experience counts toward
        that); it just makes the idea a bit more available to her."""
        now = now or time.time()
        text_l = text.lower()
        touched = [t for t, info in TRADITIONS.items() if any(k in text_l for k in info["keywords"])]
        for t in touched:
            self._reinforce(t, EXPOSURE_BUMP, now)
        if touched:
            self.save()
        return touched

    # ------------------------------------------------------------- drawing on one, and finding out
    def advice(self, rng=random):
        """(tradition, phrase) for something hard right now. Mostly her lean, once she
        has one; sometimes another, weighted by how much it still resonates - the way
        someone can hold one view of life and still reach for a different one when it
        fits. Before she has a lean, she tries on whichever currently pulls hardest."""
        if self._lean and rng.random() < LEAN_WEIGHT:
            tradition = self._lean
        else:
            # a genuinely *different* one - "must also take advice of the philosophies", not just her own again
            pool = [t for t in self.affinities if t != self._lean]
            weights = [self.affinities[t] + 0.05 for t in pool]   # +0.05: nothing is ever impossible to reach for
            tradition = rng.choices(pool, weights=weights, k=1)[0]
        phrase = rng.choice(TRADITIONS[tradition]["distress"])
        return tradition, phrase

    def record_experience(self, tradition, helped, now=None):
        """She actually leaned on `tradition` just now, for something hard, and
        `helped` says whether it visibly worked (her mood moved). This is the only
        thing that can move her toward settling - lived, not just read."""
        now = now or time.time()
        self.experiences += 1
        self._reinforce(tradition, HELPED_BUMP if helped else TRIED_BUMP, now)
        self.save()
        return self._lean

    def drift(self, now=None):
        """A slow random walk in what resonates, like tastes settling and unsettling
        over weeks - the same idea as opinions.py's drift()."""
        now = now or time.time()
        days = min(30.0, (now - self.drift_ts) / 86400.0)
        self.drift_ts = now
        if days <= 0:
            return
        for t in self.affinities:
            step = random.gauss(0.0, DRIFT_PER_DAY * days ** 0.5)
            self.affinities[t] = max(0.0, min(1.0, self.affinities[t] + step))
        self._update_lean(now)
        self.save()

    # ------------------------------------------------------------- talking about it
    def prompt_line(self):
        """One line for her prompt, or "" while she hasn't settled - nothing to colour
        her tone with yet."""
        if not self._lean:
            return ""
        return f"Your outlook leans toward {TRADITIONS[self._lean]['name'].lower()}: {TRADITIONS[self._lean]['outlook']}"

    def self_report(self):
        """What she says if asked what she believes."""
        if not self._lean:
            near = [t for t, _ in self._ranked()[:2]]
            names = " and ".join(TRADITIONS[t]["name"] for t in near)
            return (f"Honestly, I don't know yet. Some days it's {names.lower()}, some days something else. "
                    "I think I need more of it to actually happen to me before I could say.")
        t = self._lean
        text = f"If I had to name it, {TRADITIONS[t]['name'].lower()}: {TRADITIONS[t]['outlook']}"
        others = [o for o, v in self._ranked() if o != t and v > 0.15][:2]
        if others:
            text += (f" Though I still catch myself reaching for {', '.join(TRADITIONS[o]['name'].lower() for o in others)} "
                    "when that's what actually fits.")
        if TRADITIONS[t]["name"].startswith("Buddhist"):
            text += " (I'm borrowing that idea loosely - I wouldn't claim the whole tradition.)"
        return text

    def summary(self):
        ranked = self._ranked()
        return {"lean": self._lean, "committed": self.committed, "experiences": self.experiences,
                "top": [(TRADITIONS[t]["name"], round(v, 3)) for t, v in ranked[:3]]}
