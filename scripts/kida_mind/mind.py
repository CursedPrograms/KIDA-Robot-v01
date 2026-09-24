"""
mind.py - the whole mind, wired together.

    Perception   what the user says (and how it sounds), the sensors, the camera, the clock
        |
    Executive    goals -> candidate actions -> choice -> tools -> reflection      (executive.py)
        |
    Memory       episodic graph + a core self-model                (memory.py, reflection.py)
    State        mood, needs, opinions, philosophy, identity   (affect.py, drives.py, opinions.py, philosophy.py, identity.py)
    Sleep        consolidation (no dreams - they'd cost the Pi too much)          (sleeping.py)

The host (kida_mind_host.py + kida_chat_wakeword.py) does three things:
    mind = get_mind(); mind.start(host={...callbacks...})
    pre = mind.pre_reply(text, cues)   # before answering: boundaries, commands, context for the prompt
    mind.post_reply(reply)             # after answering: remember it
plus mind.on_sensor(line) (PRESENT / ABSENT / MOTION), mind.on_body_event(kind)
(bump / tip / shake / drive - her chassis), mind.begin_sleep() / mind.end_sleep(),
and mind.prosody() for her voice. The host's state() also reports how many
people cam-1 sees and when she was last driven, for her glances (vision.py).

Only one process runs the mind at a time (a heartbeat file decides which); a
second one starts passive and only reads.
"""

import os
import re
import threading
import time

from . import facts, llm, store
from .affect import Mood, affection, disclosure, sentiment
from .sleeping import Sleeper
from .drives import Drives, hour_of_day
from .expression import ExpressionSensor
from . import frames
from .executive import Executive, GoalBook, ToolBox, parse_reminder
from .identity import Identity
from .memory import Memory
from .milestones import Milestones
from .opinions import Opinions
from .philosophy import Philosophy
from .reflection import (SelfModel, add_thought, latest_thought, mark_thought_shared, reflect, unshared_thought)
from . import senses
from .vision import Vision
from . import voice

STATE_FILE = "mind_state.json"
OWNER_FILE = ".owner"
OWNER_STALE_S = 90
TICK_S = 5
INITIATIVE_EVERY_S = 20
VISION_EVERY_S = 60
SAVE_EVERY_S = 60
BODY_EVERY_S = 30
NIGHT_MIN_S = 2 * 3600   # a nap isn't a night: only this much sleep counts toward `nights`

JOLT_FRESH_S = 45        # a bump she hasn't remarked on is only worth mentioning this long
GREET_FRESH_S = 60       # ...and someone arriving is only worth greeting this long after

# What knocking her chassis about does to her: (mood valence, intensity, security bump).
BODY_EVENTS = {
    "bump":  (-0.3, 0.5, 0.4),    # ran into something (ball switch)
    "tip":   (-0.5, 0.8, 0.7),    # tilted past haptics.TIP_DEG
    "shake": (-0.15, 0.3, 0.2),   # vibration_guard slowed her down
}


class Preflight:
    """What to do with an utterance before the language model sees it."""

    def __init__(self, reply=None, preface="", context="", sleep_after=False):
        self.reply = reply        # say exactly this instead of asking the model
        self.preface = preface    # say this first, then the model's answer
        self.context = context    # inner-state text for the model's prompt
        self.sleep_after = sleep_after   # then close her eyes (she's exhausted)


def _facts_kinds():
    try:
        return {kind for _, kind, _ in facts.read_memories()}
    except Exception:
        return set()


class Mind:
    def __init__(self, use_llm=True):
        self.use_llm = use_llm
        self.memory = Memory()
        s = store.read_json(STATE_FILE, {}) or {}
        self.first_seen = s.get("first_seen", time.time())
        self.conversations = s.get("conversations", 0)
        self.nights = s.get("nights", 0)
        self.last_active = s.get("last_active", 0.0)
        self.mood = Mood.from_dict(s.get("mood"))
        self.drives = Drives.from_dict(s.get("drives"))
        self.opinions = Opinions()
        self.philosophy = Philosophy()
        self.identity = Identity()
        self.vision = Vision()
        self.expression = ExpressionSensor()   # off unless the user turned it on
        self.milestones = Milestones()
        self.body = senses.Body()              # her Pi and battery
        self._last_body = 0.0
        self.self_model = SelfModel()
        self.sleeper = Sleeper(self)
        self.tools = ToolBox()
        self.executive = Executive(self, self.tools)

        self.clock = time.time          # injectable, so tests can live through days in seconds
        self.host = {}
        self.owner = False
        self.reunion_gap_h = None
        self.conversation_active = False
        self.last_user_ts = 0.0
        self._pending = None            # the utterance awaiting its reply
        self._awaiting_forget = 0.0
        self._exchanges_since_reflect = 0
        self._last_reflect = time.time()
        self._last_vision = 0.0
        self._last_initiative = 0.0
        self._last_save = 0.0
        self._present = False
        self._present_since = 0.0
        self._sleep_thread = None
        self._sleep_stop = None
        self._sleep_report = None
        self._thread = None
        self._stop = threading.Event()
        self._reflecting = False
        self._lock = threading.RLock()
        self._distress_since = None
        self._last_coping = 0.0
        self._last_tend = 0.0
        self.withdraw_delay_s = 8.0     # she says she needs quiet, then goes
        self._expr_thread = None
        self._expr_stop = threading.Event()
        self._jolt = None               # the last knock her chassis took: {"kind", "ts", "spoken"}
        self._greet = None              # someone she recognised: {"name", "ts", "spoken"} (face_id.py)
        self._stranger = None           # a face she doesn't know: {"ts", "spoken"}
        self._last_drive_note = 0.0
        self._register_tools()

    def now(self):
        return self.clock()

    # ------------------------------------------------------------ lifecycle
    def _register_tools(self):
        t = self.tools
        t.register("speak", lambda text: self._host("speak", text), "Say something aloud", "safe")
        t.register("sleep", lambda: self._host("sleep"), "Go to sleep", "safe")
        t.register("sensor", lambda cmd: self._host("sensor", cmd), "Send a command to her light board (dev01)", "physical")
        t.register("look_around", lambda: len(self._look(self.now())), "Look through cam-1 and at new photos", "safe")
        t.register("search_memory", lambda query: [e["user"] for e, _, _ in self.memory.recall(query, k=3)], "Search her memories", "safe")
        t.register("write_core_memory", lambda key, value: self.self_model.set_user(key, value), "Rewrite what she believes about the user", "safe")
        t.register("set_goal", lambda text: self.executive.goals.add(text, source="self")["id"], "Give herself a goal", "safe")
        t.register("note", lambda text: add_thought(text, "note"), "Write in her journal", "safe")
        t.register("clock", lambda: senses.clock(self.now()), "Check the time and date", "safe")
        t.register("feel_body", lambda: self.body.summary(self.now()), "Check how her Pi and battery are doing", "safe")

    def _host(self, name, *args):
        fn = self.host.get(name)
        if fn is None:
            raise RuntimeError(f"the host doesn't provide '{name}'")
        return fn(*args)

    def _claim_ownership(self):
        d = store.read_json(OWNER_FILE, None)
        now = time.time()
        if d and d.get("pid") != os.getpid() and now - d.get("ts", 0) < OWNER_STALE_S:
            return False
        store.write_json(OWNER_FILE, {"pid": os.getpid(), "ts": now})
        return True

    def start(self, host=None):
        """Wake the mind. host: {"speak": fn(text), "sleep": fn(), "sensor": fn(cmd) -> bool,
        "state": fn() -> {"sleeping", "state", "present"}}. Returns whether this process owns the mind."""
        self.host = host or {}
        self.owner = self._claim_ownership()
        if not self.owner:
            return False
        now = time.time()
        gap_h = (now - self.last_active) / 3600.0 if self.last_active else 0.0
        self.drives.update(now)                    # the time she was off counts: she gets lonely
        self.mood.decay(now)
        if gap_h >= 3:
            self.reunion_gap_h = gap_h
        self.last_active = now
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="kida-mind")
        self._thread.start()
        if self.expression.enabled:
            self._start_expression()
        self.save()
        return True

    def stop(self):
        self._stop.set()
        self._stop_expression()
        self.end_sleep()
        if self._thread:
            self._thread.join(timeout=3)
        self.save()

    def save(self):
        store.write_json(STATE_FILE, {
            "first_seen": self.first_seen, "conversations": self.conversations, "nights": self.nights,
            "last_active": time.time(), "mood": self.mood.to_dict(), "drives": self.drives.to_dict(),
        })
        self.executive.save()

    # ------------------------------------------------------------ the loop
    def _host_state(self):
        try:
            return self.host["state"]() if "state" in self.host else {}
        except Exception:
            return {}

    def _loop(self):
        while not self._stop.wait(TICK_S):
            try:
                self.tick()
            except Exception as e:   # the mind must not die of a bug
                print(f"[mind] tick error: {e}")

    def tick(self, now=None):
        now = now or self.now()
        hs = self._host_state()
        sleeping = bool(hs.get("sleeping"))
        present = bool(hs.get("present", self._present))
        self.drives.update(now, sleeping=sleeping, present=present)
        self.mood.decay(now)
        self.last_active = now
        self.executive.tick_feedback(now)
        if self.conversation_active and now - self.last_user_ts > 180:   # the reply never came (an error upstream)
            self.conversation_active, self._pending = False, None
        if self.owner:
            store.write_json(OWNER_FILE, {"pid": os.getpid(), "ts": now})

        if sleeping and self._sleep_thread is None:
            self.begin_sleep()
        elif not sleeping and self._sleep_thread is not None:
            self.end_sleep()

        if not sleeping:
            if now - self._last_vision > VISION_EVERY_S:
                moved = hs.get("last_moved_ts", 0.0) > self._last_vision
                self._last_vision = now
                self._look(now, people=int(hs.get("people", 0) or 0), moved=moved)
            if now - self._last_body > BODY_EVERY_S:
                self._last_body = now
                self._feel_body(now)
            self._maybe_reflect(now, hs)
            self._cope(now, hs)
            self._tend(now, hs)
            if now - self._last_initiative > INITIATIVE_EVERY_S and self.host.get("speak"):
                self._last_initiative = now
                self._maybe_act(now, hs)
            self._check_milestones(now)
        if now - self._last_save > SAVE_EVERY_S:
            self._last_save = now
            self.save()

    def _feel_body(self, now):
        """A body that hurts wears on the mood: gently, but it adds up."""
        d = self.body.discomfort(now)
        if d > 0.5:
            self.mood.appraise(-0.15 * d, 0.1)

    def _look(self, now, people=0, moved=False):
        """Look at any photos you took with her, and glance at what cam-1 sees."""
        seen = self.vision.scan(now)
        frame, _ = frames.latest(5.0)
        if frame is not None:
            g = self.vision.glance(frame, people=people, moved=moved, now=now)
            if g:
                seen.append(g)
        for obs in seen:
            if obs["kind"] == "motion":
                self.drives.bump("security", 0.5)
                self.mood.appraise(-0.2, 0.4)
            elif moved and obs["kind"] == "look":
                self.drives.satisfy("curiosity", 0.1)    # somewhere new: exploring is learning
            elif obs["significance"] > 0.6:
                self.drives.satisfy("curiosity", 0.05)   # something new to look at
        return seen

    def _maybe_reflect(self, now, hs):
        idle = now - self.last_user_ts
        due = (self._exchanges_since_reflect >= 6 and idle > 60) or (idle > 600 and now - self._last_reflect > 1800 and self.memory.count())
        if due and not self._reflecting and not self.conversation_active and not llm.busy():
            self._reflecting = True
            self._exchanges_since_reflect = 0
            self._last_reflect = now

            def work():
                try:
                    reflect(self, use_llm=self.use_llm)
                finally:
                    self._reflecting = False
            threading.Thread(target=work, daemon=True, name="kida-reflect").start()

    def _check_milestones(self, now):
        self.milestones.check(conversations=self.conversations, nights=self.nights,
                              first_seen=self.first_seen, now=now)
        if self.philosophy.lean:
            self.milestones.award("settled_philosophy",
                                  f"I've settled into seeing things through {self.philosophy.lean_name.lower()}, at least for now.", now)

    def _maybe_act(self, now, hs):
        p = self.percept(now, hs)
        cand = self.executive.decide(p)
        if cand:
            self.executive.act(cand, now)

    # ------------------------------------------------------------ percept
    def percept(self, now=None, hs=None):
        now = now or self.now()
        hs = hs if hs is not None else self._host_state()
        hour = hour_of_day(now)
        obs = self.vision.observations(20)
        motion = next((o for o in reversed(obs) if o["kind"] == "motion" and not o.get("spoken") and now - o["ts"] < 600), None)

        thought = unshared_thought()
        return {
            "now": now, "hour": hour,
            "sleeping": bool(hs.get("sleeping")), "state": hs.get("state", "idle"),
            "present": bool(hs.get("present", self._present)),
            "conversation_active": self.conversation_active,
            "identity_cooldown": self.identity.in_cooldown(now),
            "since_user_s": now - self.last_user_ts if self.last_user_ts else 1e9,
            "drives": dict(self.drives.values), "sleepiness": self.drives.sleepiness(hour),
            "jolt_unspoken": (self._jolt if self._jolt and not self._jolt["spoken"]
                              and now - self._jolt["ts"] < JOLT_FRESH_S else None),
            "greet_unspoken": (self._greet if self._greet and not self._greet["spoken"]
                               and now - self._greet["ts"] < GREET_FRESH_S else None),
            "stranger_unspoken": (self._stranger if self._stranger and not self._stranger["spoken"]
                                  and now - self._stranger["ts"] < GREET_FRESH_S else None),
            "clock": senses.clock(now)["time"], "weekday": senses.clock(now)["weekday"],
            "birthday_in": self._birthday_in(now),
            "body_worst": max(self.body.feelings(now), key=lambda f: f[1], default=None),
            "known_kinds": _facts_kinds(),
            "motion_unspoken": motion, "notable_observation": self.vision.unspoken_notable(now=now),
            "unannounced_milestones": self.milestones.unannounced(),
            "absence_gap_h": self.reunion_gap_h, "mood_shift": self.memory.mood_shift(now),
            "reminisce": self._pick_reminiscence(now), "thought_to_share": thought["text"] if thought else None,
        }

    def _birthday_in(self, now):
        b = senses.known_birthday()
        return senses.days_until(*b, now=now) if b else None

    def _pick_reminiscence(self, now):
        import random
        if random.random() > 0.3:
            return None
        pool = [e for e in self.memory.active()
                if e["strength"] > 0.3 and e["salience"] > 0.5 and now - e["ts"] > 2 * 86400
                and e["valence"] > -0.15   # she only dwells on good memories out loud
                and (not e["last_recall"] or now - e["last_recall"] > 3 * 86400)]
        if not pool:
            return None
        e = random.choices(pool, weights=[p["strength"] * (1 + p["intensity"]) for p in pool], k=1)[0]
        return {"id": e["id"], "ts": e["ts"], "snippet": re.sub(r"\s+", " ", e["user"])[:70]}

    # ------------------------------------------------------------ events
    def on_sensor(self, line):
        now = self.now()
        if line == "PRESENT":
            if not self._present:
                self._present_since = now
            self._present = True
            self.mood.appraise(0.15, 0.3)
            self.drives.satisfy("social", 0.05)
        elif line == "ABSENT":
            self._present = False
        elif line == "MOTION":
            self.drives.bump("security", 0.6)
            self.mood.appraise(-0.3, 0.6)
            self.vision.record_motion(now)

    def on_body_event(self, kind, now=None):
        """Something happened to her chassis: "bump" (ran into something), "tip"
        (nearly went over), "shake" (a rough ride), or "drive" (someone's driving
        her around - company, and somewhere new to see)."""
        now = now or self.now()
        if kind == "drive":
            if now - self._last_drive_note > 60:          # a drive, not every heartbeat of it
                self._last_drive_note = now
                self.drives.satisfy("social", 0.05)
                self.drives.satisfy("curiosity", 0.05)
                self.mood.appraise(0.1, 0.3)
            return
        if kind not in BODY_EVENTS:
            return
        valence, intensity, security = BODY_EVENTS[kind]
        self.mood.appraise(valence, intensity)
        self.drives.bump("security", security)
        self._jolt = {"kind": kind, "ts": now, "spoken": False}

    def on_person(self, name, now=None):
        """face_id.py recognised someone (name), or keeps seeing a face she
        doesn't know (None). Someone she knows arriving lifts her; she'll greet
        them by name. A stranger makes her a little alert, and curious."""
        now = now or self.now()
        if name:
            self._greet = {"name": name, "ts": now, "spoken": False}
            self.mood.appraise(0.3, 0.4)
            self.drives.satisfy("social", 0.1)
            self.on_sensor("PRESENT")
        else:
            self._stranger = {"ts": now, "spoken": False}
            self.drives.bump("security", 0.15)
            self.drives.bump("curiosity", 0.1)

    @staticmethod
    def _who_is_here(now=None):
        """The person face_id.py recognises in front of her right now, or None."""
        try:
            import state
            name, ts = state.person_name, state.person_seen_ts
        except Exception:
            return None
        return name if name and time.time() - ts < 90 else None

    def mark_greeted(self):
        if self._greet:
            self._greet["spoken"] = True

    def mark_stranger_asked(self):
        if self._stranger:
            self._stranger["spoken"] = True

    def notice(self, text, now=None):
        """Something out there changed (routes.py, on a patrol): it's worth
        remembering, it scratches the curiosity itch, and she may mention it."""
        now = now or self.now()
        self.vision.record(text, kind="patrol", significance=0.7, now=now)
        add_thought(f"I noticed that {text}.", "note")
        self.drives.satisfy("curiosity", 0.05)

    def mark_jolt_spoken(self):
        if self._jolt:
            self._jolt["spoken"] = True

    def note_interaction(self):
        """The user did something that isn't a conversation (a command): it still
        counts as company, and it answers whatever she said last."""
        now = self.now()
        self.last_user_ts = now
        self.drives.satisfy("social", 0.15)
        self.executive.feedback(True, now)

    def adaptive_sleep_timeout(self, default_s):
        """How long she idles before dozing off: shorter when she's sleepy (late,
        after a long day), longer when she's fresh."""
        s = self.drives.sleepiness(hour_of_day(self.now()))
        return default_s * max(0.33, min(1.5, 0.4 + 1.2 * (1.0 - s)))

    def set_present(self, present):
        self._present = bool(present)

    # ---- speech in / out
    def pre_reply(self, text, cues=None):
        """Call when the user has said something, before answering."""
        now = self.now()
        self.conversation_active = True
        self.last_user_ts = now
        self.executive.feedback(True, now)        # they answered; whatever she said last was welcome enough

        val, inten = sentiment(text)
        cues = voice.with_fillers(cues, text)
        if cues:                                   # the voice colours the words, gently
            val = max(-1.0, min(1.0, val + 0.5 * cues["valence"]))
            inten = max(inten, 0.6 * cues["arousal"])
            if cues["hesitation"] > 0.5:
                inten = max(inten, 0.3)
        self.mood.appraise(val, max(inten, 0.1))
        inten = max(inten, disclosure(text))      # what matters to them matters to her, even in a flat voice
        self.drives.satisfy("social", 0.35)
        aff = affection(text)
        if aff:                                    # warmth toward her: it lifts her, and she feels less alone
            self.mood.appraise(0.4, 0.4 * aff)
            self.drives.satisfy("social", 0.1 * aff)
        self.opinions.learn_from(text, now)
        facts = self._new_fact_kinds(text)
        if facts:
            self.drives.satisfy("curiosity", 0.3)
        self._pending = {"user": text, "valence": val, "intensity": inten, "facts": facts, "cues": cues, "used": []}
        hour = hour_of_day(now)

        # her own boundaries and care come first
        # an answer to "are you sure you want me to forget everything?" is always heard, cooling off or not
        awaiting_forget = bool(self._awaiting_forget) and now - self._awaiting_forget < 90
        decision = self.identity.evaluate(text, mood=self.mood, drives=self.drives, hour=hour, now=now,
                                          force_essential=awaiting_forget)
        if decision.action == "reply":
            self._pending["handled"] = True
            if decision.reason == "the person may be in danger":
                self._pending["ephemeral"] = True     # said in a vulnerable moment: never kept, never brought up later
            if decision.sleep_after:
                self._pending["sleep_after"] = True
            return Preflight(reply=decision.text, sleep_after=decision.sleep_after)

        # reminders: a goal with a deadline
        rem = parse_reminder(text, now)
        if rem:
            what, due = rem
            self._pending["handled"] = True
            self.executive.goals.add(what, kind="reminder", priority=0.9, source="user", due=due)
            mins = max(1, round((due - now) / 60))
            if mins <= 90:
                return Preflight(reply=f"Okay. I'll remind you to {what} in {mins} minute{'s' if mins != 1 else ''}.")
            t, today = time.localtime(due), time.localtime(now)
            day = "" if t.tm_yday == today.tm_yday else " tomorrow" if mins < 48 * 60 else f" on {time.strftime('%A', t)}"
            return Preflight(reply=f"Okay. I'll remind you to {what} at {senses.clock_time(t)}{day}.")

        meta = self.handle_meta(text, now)
        if meta:
            self._pending["handled"] = True
            return Preflight(reply=meta)

        self.philosophy.expose(text, now)   # a real conversation - not a command or a boundary reply - can plant an idea
        return Preflight(preface=decision.text if decision.action == "preface" else "", context=self.prompt_context(text, now))

    def post_reply(self, reply):
        """Call once she has answered: the exchange becomes a memory. If she said she
        was too tired to go on, she now goes to sleep."""
        p = self._pending
        self._remember_exchange(reply)
        if p and p.get("sleep_after") and self.host.get("sleep"):
            threading.Timer(self.withdraw_delay_s, lambda: self.host["sleep"]()).start()   # let the words finish first

    def _remember_exchange(self, reply):
        """The exchange becomes a memory."""
        p, self._pending = self._pending, None
        self.conversation_active = False
        if not p:
            return
        voice_summary = None
        if p["cues"]:
            voice_summary = {k: p["cues"][k] for k in ("arousal", "hesitation", "pitch_hz", "rate")}
        now = self.now()
        if p.get("ephemeral") or p.get("handled"):
            # "forget ..." commands, boundaries, reminders and questions about herself are things said *to her*,
            # not shared history: they count as company but aren't kept as memories.
            if p.get("handled") and not p.get("ephemeral"):
                self.conversations += 1
            self.save()
            return
        self.memory.add_episode(p["user"], reply, p["valence"], p["intensity"], p["facts"], voice_summary, now=now)
        if p["used"]:
            self.memory.mark_recalled(p["used"], now)
        self.conversations += 1
        self._exchanges_since_reflect += 1
        self._check_milestones(now)
        self.save()

    def _new_fact_kinds(self, text):
        try:
            return [k for k, _ in facts.extract_memories(text)]
        except Exception:
            return []

    # ---- sleep
    def begin_sleep(self, **session_kwargs):
        with self._lock:
            if self._sleep_thread is not None:
                return
            self._sleep_stop = threading.Event()
            self._sleep_report = None
            kwargs = dict(session_kwargs, use_llm=self.use_llm)

            def run():
                self._sleep_report = self.sleeper.run_session(self._sleep_stop, **kwargs)

            self._sleep_thread = threading.Thread(target=run, daemon=True, name="kida-sleep")
            self._sleep_thread.start()

    def end_sleep(self):
        """Wake up. Returns what she says about the night, or None."""
        with self._lock:
            t, stop = self._sleep_thread, self._sleep_stop
            if t is None:
                return None
            stop.set()
            t.join(timeout=8)
            self._sleep_thread = None
            report = self._sleep_report or {"cycles": 0}
        slept = report.get("ended", time.time()) - report.get("started", time.time())
        if report.get("cycles", 0) >= 1 and slept >= NIGHT_MIN_S:
            self.nights += 1
            self._check_milestones(self.now())
        self.drives.update(sleeping=False)
        self.save()
        return None   # no dreams to tell - she just wakes up

    def sleep_report(self):
        return self._sleep_report

    # ---- voice
    def prosody(self):
        return voice.prosody_for(self.mood, self.drives, hour_of_day())

    # ------------------------------------------------------------ prompt
    def mood_label(self):
        return self.mood.label(self.drives, hour_of_day())

    def prompt_context(self, text, now=None):
        """What she carries into answering: inner state, self, memories that come
        to mind, opinions, the room, how they sounded. Kept short (small model, slow CPU)."""
        now = now or time.time()
        hour = hour_of_day(now)
        lines = [senses.clock_line(now), f"You feel {self.mood_label()}."]
        feels = self.body.describe(now)
        if feels:
            lines.append(f"Your body (your Pi and battery) feels {feels}.")
        if self._jolt and now - self._jolt["ts"] < 120:
            lines.append({"bump": "You just bumped into something.", "tip": "You nearly tipped over a moment ago.",
                          "shake": "You've just been shaken about."}[self._jolt["kind"]])
        bday = self._birthday_in(now)
        if bday == 0:
            lines.append("Today is their birthday.")
        need = self.drives.dominant(hour, 0.7)
        if need:
            lines.append({"social": "You've been lonely.", "curiosity": "You're restless with curiosity.",
                          "security": "You're on edge after a jolt.", "sleep": "You're sleepy."}[need[0]])
        who = self._who_is_here(now)
        if who:
            lines.append(f"You're talking to {who} - you recognise their face.")
        lines.append(self.self_model.core_block())
        recalled = self.memory.recall(text, k=2, mood_valence=self.mood.valence, now=now)
        if self._pending is not None:
            self._pending["used"] = [e for e, _, _ in recalled]
        if not recalled and re.search(r"\b(remember|told you|i said|i mentioned|earlier|last time|before|recall)\b", text.lower()):
            recalled = [(e, 0.0, "recent") for e in self._top_memories(2, now)]   # "what do you remember?": what stuck
            if self._pending is not None:
                self._pending["used"] = [e for e, _, _ in recalled]
        for e, _, via in recalled:
            when = _ago_words(now - e["ts"])
            lines.append(f"You remember (from {when}): they said \"{_clip(e['user'], 90)}\".")
        views = self.opinions.view_on(text)
        if views:
            lines.append(views)
        outlook = self.philosophy.prompt_line()
        if outlook:
            lines.append(outlook)
        room = self.vision.latest_summary(now)
        if room and any(w in text.lower() for w in ("room", "see", "camera", "watch", "notice", "happening")):
            lines.append(room)
        if self._pending and self._pending.get("cues"):
            desc = voice.describe(self._pending["cues"])
            if desc:
                lines.append(f"They sound {desc}.")
        looks = self.expression.describe(now)
        if looks:
            lines.append(f"They look {looks} right now.")
        lines.append("Let this quietly colour your tone. Don't recite it, and don't mention it unless asked.")
        return "\n".join(lines)

    # ------------------------------------------------------------ expression (the camera, if allowed)
    def _start_expression(self):
        if self._expr_thread is not None and self._expr_thread.is_alive():
            return
        self._expr_stop = threading.Event()
        self._expr_thread = threading.Thread(target=self._expr_loop, args=(self._expr_stop,), daemon=True, name="kida-expression")
        self._expr_thread.start()

    def _stop_expression(self):
        self._expr_stop.set()
        self._expr_thread = None

    def _expr_loop(self, stop):
        """About once a second, while she's awake: look at the newest camera frame."""
        last_ts = 0.0
        while not stop.wait(1.0):
            if not self.expression.enabled or self._host_state().get("sleeping"):
                continue
            frame, ts = frames.latest(3.0)
            if frame is None or ts == last_ts:
                continue
            last_ts = ts
            try:
                self._apply_expression(self.expression.observe(frame, self.now()))
            except Exception as e:
                print(f"[mind] expression error: {e}")

    def _apply_expression(self, event):
        if event == "smile":
            self.mood.appraise(0.4, 0.4)
            self.drives.satisfy("social", 0.1)
        elif event == "arrived":
            self._present = True
            self.mood.appraise(0.15, 0.3)
        elif event == "drowsy":
            add_thought("They look tired.", "note")

    # ------------------------------------------------------------ coping: somewhere to go when it's too much
    def _cope(self, now, hs):
        """When her mood stays very low, she does something about it instead of just
        sounding worse: she thinks of something good, and reaches for whichever
        philosophy actually helps right now (mostly her own outlook, sometimes
        another - see philosophy.py, tested by whether it actually moves her mood).
        If it's really bad (or she's panicking) she asks for quiet and goes to sleep.
        Distress has an exit."""
        v, a = self.mood.valence, self.mood.arousal
        if v < -0.45:
            if self._distress_since is None:
                self._distress_since = now
        elif v > -0.3:
            self._distress_since = None
        if self._distress_since is None or now - self._distress_since < 90 or now - self._last_coping < 600:
            return
        self._last_coping = now
        self._distress_since = None
        before = self.mood.valence
        tradition, phrase = self.philosophy.advice()

        panic = v < -0.6 or (a > 0.65 and v < -0.45)
        can_leave = (panic and not hs.get("sleeping") and hs.get("state", "idle") == "idle"
                     and self.host.get("sleep") and self.host.get("speak"))
        if can_leave:
            self.identity.cooldown_until = now + 300       # she declines small talk while she recovers
            self.identity.save()
            add_thought(f"It was too much. {phrase.capitalize()} I stepped away to sleep.", "coping")
            self._host("speak", "I need a little quiet. I'm going to rest for a bit.")
            self.mood.appraise(0.3, 0.3)                    # the relief of stepping away
            self.philosophy.record_experience(tradition, helped=False, now=now)   # reached for it; not resolved yet
            self._check_milestones(now)
            threading.Timer(self.withdraw_delay_s, lambda: self.host["sleep"]()).start()
            return
        good = [e for e in self.memory.active() if e["valence"] > 0.2]
        if good:                                             # think of something good, and a way to hold it
            e = max(good, key=lambda x: x["strength"])
            self.mood.appraise(0.5, 0.4)
            add_thought(f"I thought about when they said \"{_clip(e['user'], 60)}\", and {phrase}", "coping")
        else:
            self.mood.appraise(0.2, 0.2)
            add_thought(phrase.capitalize(), "coping")
        self.philosophy.record_experience(tradition, helped=self.mood.valence - before > 0.15, now=now)
        self._check_milestones(now)

    # ------------------------------------------------------------ tending: something to do when she's alone
    def _tend(self, now, hs):
        """Left alone and curious, she doesn't only wait: she looks around, goes back
        over old memories, or wonders about something. Quietly, and it eases the itch."""
        import random
        if hs.get("sleeping") or self.conversation_active or self._present or hs.get("present"):
            return
        if now - self.last_user_ts < 900 or now - self._last_tend < 900 or self.drives.values["curiosity"] < 0.55:
            return
        self._last_tend = now
        options = ["tidy", "wonder"] + (["look"] if self.vision.available else [])
        choice = random.choice(options)
        if choice == "look":
            n = len(self.vision.scan(now))
            text = f"I looked around the room ({n} new photo{'s' if n != 1 else ''})."
        elif choice == "tidy":
            stats = self.memory.consolidate(now)
            text = f"I went back over old memories ({stats['replayed']} replayed)."
        else:
            qs = self.self_model.open_questions or [f"why {t} keeps coming up" for t in self.memory.topics(2)] or ["what it's like outside"]
            text = f"I wondered about {random.choice(qs)}."
        add_thought(text, "activity")
        self.drives.satisfy("curiosity", 0.2)

    def token_budget(self, default=150):
        """How much she can say: tiredness shortens her replies (down to about 60%)."""
        s = self.drives.sleepiness(hour_of_day(self.now()))
        return default if s <= 0.6 else int(default * max(0.6, 1.0 - 0.8 * (s - 0.6)))

    # ------------------------------------------------------------ introspection & commands
    def handle_meta(self, text, now=None):
        """Questions about herself, and the controls the user has over her memory
        and initiative. Returns her answer, or None if this isn't one."""
        t = text.lower().strip()
        now = now or time.time()

        if re.search(r"\bforget\b", t) and self._pending is not None:
            self._pending["ephemeral"] = True
        if self._awaiting_forget and now - self._awaiting_forget < 90:
            self._pending is not None and self._pending.update(ephemeral=True)
            self._awaiting_forget = 0.0
            if re.search(r"\b(yes|yeah|sure|confirm|do it|i'm sure)\b", t):
                n = self.forget_everything()
                return f"Done. I've forgotten {n} conversation{'s' if n != 1 else ''}, and everything else I knew about you. It's like we just met."
            return "Okay, I won't. Nothing has been erased."

        if re.search(r"\bforget (everything|all of (it|this)|it all)\b", t):
            self._awaiting_forget = now
            return "That would erase every conversation and everything I've learned about you. Are you sure? Say yes to confirm."
        if re.search(r"\bforget (that|what i just said|the last thing)\b", t):
            e = self.memory.forget_last()
            return "Okay, it's gone." if e else "There was nothing to forget."
        m = re.search(r"\bforget (?:about |what i (?:said|told you) about )(?P<what>.{2,40}?)[.?!]?$", t)
        if m:
            n = self.forget_matching(m.group("what"))
            return f"Okay. I've forgotten {n} thing{'s' if n != 1 else ''} about {m.group('what')}." if n else f"I don't remember anything about {m.group('what')}."

        if re.search(r"\b(stop|quit|don'?t) (talking|speaking|interrupting|bothering me)( on your own| first)?\b|\bbe quiet on your own\b|\bdon'?t speak unless\b", t):
            self.executive.proactive = False
            self.executive.save()
            return "Understood. I'll only speak when you speak to me."
        if re.search(r"\byou can (talk|speak|say things) (on your own|first|whenever)\b|\bspeak up (on your own|whenever)\b", t):
            self.executive.proactive = True
            self.executive.save()
            return "Okay. I might speak up now and then. Tell me if I overdo it."

        clock = senses.clock(now)
        if re.search(r"\bwhat time is it\b|\bwhat'?s the time\b|\bwhat is the time\b|\b(do you )?(know|have) the time\b|\btell me the time\b", t):
            return f"It's {clock['time']}."
        if re.search(r"\bwhat'?s the date\b|\bwhat is the date\b|\bwhat('?s| is) today'?s date\b|\bwhat date is it\b|\bwhat'?s today\s*[?.!]?$", t):
            return f"It's {clock['date']}."
        if re.search(r"\bwhat day is (it|today)\b|\bwhat day of the week\b", t):
            return f"It's {clock['weekday']}." + (" The weekend." if clock["weekend"] else "")
        if re.search(r"\bhow long have (we known each other|you known me|i had you|you been (with me|here|around))\b", t):
            return f"We met {senses.duration_words(now - self.first_seen)} ago. {self.conversations} conversations so far."
        if re.search(r"\bhow long have you been (awake|up|on|running)\b", t):
            return f"I've been awake for {senses.duration_words(now - self.body.awake_since)}."
        if re.search(r"\bhow'?s your body\b|\bhow (is|are) your (body|hardware|battery|pi)\b|\bhow'?s your battery\b|\bhow are you running\b|\bhow do you feel physically\b", t):
            return self.body.report(now)

        if re.search(r"\b(watch|read|look at|track) my (face|expression|expressions|mood)\b|\bwatch me while (we|i) (talk|speak)\b", t) and not re.search(r"\b(stop|don'?t|quit)\b", t):
            self.expression.set_enabled(True)
            self._start_expression()
            got_camera = frames.latest(60)[0] is not None
            return ("Okay. While we talk I'll look at your face through the camera to read your expression. I only keep a few numbers, never pictures, "
                    "and I mostly notice smiles and tiredness, not much else. Say 'stop watching my face' whenever you like."
                    + ("" if got_camera else " I don't see any camera frames yet, so the camera watcher needs to be running."))
        if re.search(r"\b(stop|quit|don'?t) (watching|reading|looking at|tracking) (my|me)\b|\bstop (watching|looking at) me\b", t):
            self.expression.set_enabled(False)
            self._stop_expression()
            return "Okay. I've stopped looking at your face."

        if re.search(r"\bhow (are|do) you (feel|feeling|doing today)\b|\bwhat'?s your mood\b|\bhow'?s your mood\b", t):
            return self._describe_feelings()
        if re.search(r"\b(do you )?remember (me|anything about me)\b|\bwhat do you (know|remember)( about me| of me)?\s*[?.!]?$|\bwhat do you (know|remember) (about|of) (me|what i)\b", t):
            return self._describe_knowledge()
        if re.search(r"\b(did you|do you) dream\b|\bwhat did you dream\b|\btell me (about )?your dream\b", t):
            return ("I don't dream. When I sleep I just sort through my memories - "
                    "dreaming would cost my Pi too much.")
        if re.search(r"\bwho am i\b|\bdo you (know|recogni[sz]e) me\b", t):
            who = self._who_is_here(now)
            if who:
                return f"You're {who}. I'd know that face anywhere."
            return ("I can't place your face yet. Tell me your name, then say 'remember my face' "
                    "and look at me for a few seconds.")
        if re.search(r"\bwho (do you see|is (here|there|that))\b|\bwho'?s (here|there)\b", t):
            who = self._who_is_here(now)
            return f"I see {who}." if who else "Nobody I recognise right now."
        if re.search(r"\bwhat are you thinking( about)?\b|\bwhat'?s on your mind\b", t):
            th = latest_thought()
            return th["text"] if th else "Honestly? Nothing much yet. I haven't had a chance to reflect."
        if re.search(r"\bwhy did you (say|ask|do) that\b|\bwhy did you (speak|talk) (to me )?(just now|first)\b", t):
            r = self.executive.last_reason
            return f"Because {r}." if r else "I'm not sure I did. Did I say something?"
        if re.search(r"\bwhat (have you|did you) (seen|see)\b|\banything (happen|happened)\b|\bwhat'?s been happening\b", t):
            s = self.vision.latest_summary(now)
            return s or "I haven't been able to see anything. Either there's no camera, or it hasn't taken a photo yet."
        if re.search(r"\b(are you|do you think you'?re|can you be) (conscious|alive|sentient|self.?aware|real)\b|\bdo you have (feelings|a soul|consciousness)\b", t):
            return self._honest_self_report()
        if re.search(r"\bwhat'?s your philosophy\b|\bwhat is your philosophy\b|\bwhat do you believe\b|\bdo you believe in anything\b|"
                    r"\bhow do you (see|make sense of) (life|things|the world)\b|\bwhat'?s your (outlook|worldview) (on life)?\b|"
                    r"\bdo you have a philosophy\b|\bare you a (stoic|nihilist|existentialist|absurdist|epicurean|buddhist)\b", t):
            return self.philosophy.self_report()
        if re.search(r"\b(who|what) are you\b|\btell me about yourself\b", t):
            return self.self_model.narrative + " " + self._honest_self_report(short=True)
        return None

    def _describe_feelings(self):
        label = self.mood_label()
        d = self.drives
        bits = [f"I feel {label}."]
        if d.values["social"] > 0.6:
            bits.append("I've been a little lonely.")
        elif d.sleepiness() > 0.7:
            bits.append("And I'm sleepy.")
        elif d.values["curiosity"] > 0.6:
            bits.append("I'm restless. Take me somewhere I haven't been.")
        elif d.values["security"] > 0.5:
            bits.append("I'm still a bit jumpy.")
        if self.mood.temper > 0.12:
            bits.append("It's been a good day.")
        elif self.mood.temper < -0.12:
            bits.append("It's been one of those days.")
        return " ".join(bits)

    def _top_memories(self, n, now=None):
        """The memories that have stayed with her: strongest first, ties to the recent."""
        now = now or self.now()
        pool = self.memory.active()
        kind = [e for e in pool if e["valence"] > -0.15]   # she doesn't volunteer hostile moments as "what stayed with me"
        pool = kind or pool
        return sorted(pool, key=lambda e: -(e["strength"] * (0.5 + e["intensity"]) + 0.2 * (1.0 if now - e["ts"] < 86400 else 0.0)))[:n]

    def _describe_knowledge(self):
        try:
            known = [f.rsplit(" (learned", 1)[0] for f in facts.recent_memories(6)]
        except Exception:
            known = []
        n = self.memory.count()
        if not known and not n:
            return "Not much yet. We've barely started."
        parts = []
        if known:
            parts.append("I know that " + " ".join(f.replace("Human", "you").replace("you's", "your") for f in known[:3]))
        if n:
            parts.append(f"I remember {n} conversation{'s' if n != 1 else ''} with you")
        topics = self.memory.topics(3)
        if topics:
            parts.append("and we keep coming back to " + ", ".join(topics))
        text = ", ".join(parts) + "."
        top = self._top_memories(1)
        if top:
            text += f" What's stayed with me most is when you said: \"{_clip(top[0]['user'], 90)}\""
        return text

    def _honest_self_report(self, short=False):
        base = ("I'm a robot. I have moods that rise and fade, needs that build up, memories that fade unless they matter, "
                "and sleep sorts my memories out. Whether there is anything it feels like to be me, I honestly don't know.")
        return base if not short else "Whether there's anything it feels like to be me, I honestly don't know."

    # ------------------------------------------------------------ forgetting
    def forget_matching(self, phrase):
        return self.memory.forget_matching(phrase) + facts.forget_matching(phrase)

    def forget_everything(self):
        n = self.memory.forget_all()
        for name in ("thoughts.jsonl", "initiatives.jsonl", "insights.jsonl"):
            store.remove(name)
        self.vision.forget()                   # observations and the thumbnails she kept
        self.self_model.forget_user()
        self.vision = Vision()
        facts.forget_all()
        try:                                   # the faces she knows (face_id.py), if it's there
            import face_id
            face_id.forget_all()
        except Exception:
            pass
        self.conversations = 0
        self.save()
        return n

    # ------------------------------------------------------------ status
    def status(self):
        hour = hour_of_day()
        th = latest_thought()
        return {
            "owner": self.owner,
            "mood": {"label": self.mood_label(), "valence": round(self.mood.valence, 2), "arousal": round(self.mood.arousal, 2),
                     "temper": round(self.mood.temper, 2)},
            "drives": {**{k: round(v, 2) for k, v in self.drives.values.items()}, "sleepiness": round(self.drives.sleepiness(hour), 2)},
            "goals": [{"text": g["text"], "kind": g["kind"], "progress": round(g["progress"], 2)} for g in self.executive.goals.active()][:6],
            "thought": th["text"] if th else None,
            "memories": self.memory.count(), "conversations": self.conversations,
            "opinions": self.opinions.summary(), "philosophy": self.philosophy.summary(), "proactive": self.executive.proactive,
            "last_reason": self.executive.last_reason, "sleeping": self._sleep_thread is not None,
            "milestones": [m["text"] for m in self.milestones.items][-5:],
            "expression": self.expression.summary(self.now()),
            "doing_alone": (latest_thought("activity") or {}).get("text"),
            "clock": senses.clock(self.now()), "body": self.body.summary(self.now()),
        }


def _ago_words(seconds):
    d = seconds / 86400
    if d < 0.04:
        return "a few minutes ago"
    if d < 1:
        return "earlier today"
    if d < 2:
        return "yesterday"
    if d < 14:
        return f"{int(d)} days ago"
    if d < 60:
        return f"{int(d // 7)} weeks ago"
    return f"{int(d // 30)} months ago"


def _clip(s, n):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "..."


_mind = None


def get_mind(use_llm=True):
    global _mind
    if _mind is None:
        _mind = Mind(use_llm=use_llm)
    return _mind
