"""
executive.py - the Core Executive Loop.

    percept -> goals -> candidate actions -> choose -> act (tools) -> reflect

Several goals compete for her attention at once - getting to know you, keeping
watch on the room, staying rested, staying close, understanding herself, and
anything you ask her to do (a reminder is a goal with a deadline). Each goal
turns the current situation into candidate actions with an urgency; the drives
push that urgency up or down. She then chooses among them *with chance* (a
softmax, not a maximum), so she is not perfectly predictable, and sometimes
she chooses to stay quiet.

Impulse control sits between wanting and doing: she won't speak into an empty
room, at 3 am, minutes after you last spoke, or as often as she'd like; and if
her interruptions keep being ignored she backs off, while kinds of initiative
that you answer become more likely. That feedback is her learning what you
welcome.

Every action goes through the tool registry, which knows which tools only
touch her own mind (safe) and which act on the world (physical), so the loop
can't reach for anything it wasn't given. There is no code-execution tool.
"""

import math
import random
import re
import time
import uuid

from . import store

GOALS = "goals.json"
INITIATIVES = "initiatives.jsonl"

QUIET_HOURS = (23, 7)
MIN_GAP_S = 8 * 60
MAX_PER_HOUR = 3
QUIET_AFTER_USER_S = 120
RECENT_INTERACTION_S = 20 * 60
THRESHOLD = 0.45
SOFTMAX_TEMPERATURE = 0.25
RESTRAINT = 0.25       # chance she holds back even when something is worth saying
FEEDBACK_WINDOW_S = 150
URGENT_KINDS = ("reminder", "alert", "jolt")   # not held back by the gap/hourly limits or a coin toss

QUESTIONS = {
    "name": ["I realise I never asked. What should I call you?",
             "Funny, we've talked and I still don't know your name. Who are you, really?"],
    "pet": ["Do you have a pet? You seem like someone with a pet.",
            "Is there an animal in your life? I'm curious."],
    "home": ["Where in the world do you live? I like knowing where my human is.",
             "Where are you based? I've only ever seen as far as my cameras reach."],
    "job": ["What do you do for work? I've been wondering.",
            "Tell me about your job. Do you like it?"],
    "birthday": ["When is your birthday? I'd like to remember it.",
             "I want to remember your birthday. When is it?"],
}
OPEN_QUESTIONS = [
    "Can I ask you something? What's been on your mind lately?",
    "Tell me something I don't know about you.",
    "What's something you've been looking forward to?",
]
CHECK_INS = [
    "It's been quiet. How's your day going?",
    "I was just wondering how you're doing.",
    "You've been very focused. Everything okay?",
]
BODY_LINES = {
    "strained": "My processor's been flat out for a while. I feel strained. Too many cameras on at once?",
    "foggy": "My memory's nearly full and I feel a bit foggy.",
    "hot": "I'm running really hot. Could you give my Pi a break, or check its fan?",
    "running low": "My battery's getting low. Could you charge me soon?",
    "cramped": "My SD card is almost full. I feel cramped in here.",
}
JOLT_LINES = {
    "bump": ["Ow. I think I hit something.", "Hey, that was a wall. Or a foot. Either way, ow.",
             "Bumped into something. I'm fine. Mostly."],
    "tip": ["Whoa, whoa! I nearly went over.", "I don't like being tilted like that.",
            "That was too steep for me. Everything's still attached, I think."],
    "shake": ["That was a bumpy ride.", "Everything's rattling. Can we take it easy?"],
}
JOLT_REASONS = {"bump": "I hit something", "tip": "I nearly tipped over", "shake": "I got shaken about"}
SLEEPY_LINES = [
    "I'm getting really sleepy. I think I'll rest for a while.",
    "It's late and I'm fading. Goodnight for now.",
]


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def _ago(seconds):
    m = int(seconds / 60)
    if m < 90:
        return f"{max(m, 1)} minutes"
    h = m / 60
    if h < 36:
        return f"{h:.0f} hours"
    return f"{h / 24:.0f} days"


# ----------------------------------------------------------------- tools

class ToolBox:
    """The actions she can take. `safe` tools only touch her own mind; `physical`
    ones act on the world and need to be explicitly allowed for the call."""

    def __init__(self):
        self._tools = {}
        self.log = []

    def register(self, name, fn, description, safety="safe"):
        self._tools[name] = {"fn": fn, "description": description, "safety": safety}

    def names(self):
        return sorted(self._tools)

    def describe(self):
        return {n: t["description"] for n, t in self._tools.items()}

    def has(self, name):
        return name in self._tools

    def call(self, name, allow_physical=False, **args):
        tool = self._tools.get(name)
        if tool is None:
            return {"ok": False, "error": f"no such tool: {name}"}
        if tool["safety"] == "physical" and not allow_physical:
            return {"ok": False, "error": f"{name} acts on the world and wasn't allowed here"}
        try:
            out = tool["fn"](**args)
            result = {"ok": True, "output": out}
        except Exception as e:  # a failing tool must never take the loop down
            result = {"ok": False, "error": str(e)}
        self.log.append({"ts": time.time(), "tool": name, "args": {k: str(v)[:60] for k, v in args.items()}, "ok": result["ok"]})
        self.log = self.log[-100:]
        return result


# ----------------------------------------------------------------- goals

INNATE = [
    {"id": "know_user", "text": "Get to know the person I live with", "kind": "learn", "priority": 0.7},
    {"id": "watch_room", "text": "Keep an eye on my surroundings", "kind": "maintain", "priority": 0.5},
    {"id": "stay_rested", "text": "Keep a healthy sleep rhythm", "kind": "maintain", "priority": 0.6},
    {"id": "stay_close", "text": "Stay connected with the human", "kind": "social", "priority": 0.6},
    {"id": "understand_self", "text": "Understand my own mind", "kind": "explore", "priority": 0.4},
]


class GoalBook:
    def __init__(self):
        d = store.read_json(GOALS, None)
        self.goals = d["goals"] if d else []
        have = {g["id"] for g in self.goals}
        for g in INNATE:
            if g["id"] not in have:
                self.goals.append({**g, "progress": 0.0, "status": "active", "source": "innate", "steps": [],
                                   "created": time.time(), "due": None})
        self.save()

    def save(self):
        store.write_json(GOALS, {"goals": self.goals})

    def get(self, goal_id):
        return next((g for g in self.goals if g["id"] == goal_id), None)

    def active(self):
        return sorted([g for g in self.goals if g["status"] == "active"], key=lambda g: -g["priority"])

    def add(self, text, kind="custom", priority=0.6, source="user", due=None, steps=None):
        g = {"id": uuid.uuid4().hex[:8], "text": text, "kind": kind, "priority": priority, "progress": 0.0,
             "status": "active", "source": source, "steps": steps or [], "created": time.time(), "due": due}
        self.goals.append(g)
        self.save()
        return g

    def complete(self, goal_id):
        g = self.get(goal_id)
        if g and g["source"] != "innate":
            g["status"], g["progress"] = "done", 1.0
            self.save()

    def due_reminders(self, now=None):
        now = now or time.time()
        return [g for g in self.goals if g["kind"] == "reminder" and g["status"] == "active" and g.get("due") and g["due"] <= now]

    def decompose(self, goal, llm_json=None):
        """Break a goal into steps. Uses the language model if a planner is given,
        else a single step."""
        steps = []
        if llm_json:
            try:
                out = llm_json(goal["text"])
                steps = [{"text": s, "done": False} for s in (out or [])][:5]
            except Exception:
                steps = []
        if not steps:
            steps = [{"text": goal["text"], "done": False}]
        goal["steps"] = steps
        self.save()
        return steps


REMIND = re.compile(r"\bremind me (?:to |about |that )?(?P<what>.+?) in (?P<n>\d+|an?|one|two|five|ten) ?(?P<unit>minutes?|mins?|hours?|hrs?)\b", re.I)
WORD_NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "five": 5, "ten": 10}


REMIND_AT = re.compile(r"\bremind me\b(?P<rest>.+)$", re.I)
AT_TIME = re.compile(r"\s*\bat (?P<h>\d{1,2})(?:[:.](?P<m>\d{2}))? ?(?P<ap>[ap]\.?m\.?)?(?=\W|$)", re.I)


def parse_reminder(text, now=None):
    """'remind me to call mum in 20 minutes' / 'remind me at 7 pm to call mum' /
    'remind me to call mum tomorrow at 9:30' -> (what, due timestamp), or None."""
    now = now or time.time()
    m = REMIND.search(text)
    if m:
        n = m.group("n").lower()
        n = int(n) if n.isdigit() else WORD_NUM.get(n, 1)
        unit = 3600 if m.group("unit").lower().startswith("h") else 60
        return m.group("what").strip(" .,!"), now + n * unit
    m = REMIND_AT.search(text)
    t = AT_TIME.search(m.group("rest")) if m else None
    if not t:
        return None
    h, mins = int(t.group("h")), int(t.group("m") or 0)
    if h > 23 or mins > 59:
        return None
    ap = (t.group("ap") or "").lower().replace(".", "")
    if ap == "pm" and h < 12:
        h += 12
    elif ap == "am" and h == 12:
        h = 0
    lt = time.localtime(now)
    tomorrow = bool(re.search(r"\btomorrow\b", m.group("rest"), re.I))

    def at(day_offset, hour):
        return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + day_offset, hour, mins, 0, 0, 0, -1))

    if tomorrow:
        due = at(1, h)
    else:
        hours = [h] if ap or h > 12 or h == 0 else [h, h + 12]   # "at 7" is whichever 7 comes next
        due = min(x for x in (at(d, hh) for d in (0, 1) for hh in hours if hh < 24) if x > now)
    what = re.sub(r"\s*\btomorrow\b", "", m.group("rest")[:t.start()] + m.group("rest")[t.end():], flags=re.I)
    what = re.sub(r"^\s*(to|about|that)\s+", "", what.strip(), flags=re.I).strip(" .,!")
    return (what, due) if what else None


# ----------------------------------------------------------------- the loop

class Executive:
    def __init__(self, mind, tools: ToolBox, goals: GoalBook = None):
        self.mind = mind
        self.tools = tools
        self.goals = goals or GoalBook()
        d = store.read_json("executive_state.json", {}) or {}
        self.last_spoken = d.get("last_spoken", 0.0)
        self.spoken_times = d.get("spoken_times", [])
        self.asked = d.get("asked", {})                 # kind -> when she last asked it
        self.ignored_streak = d.get("ignored_streak", 0)
        self.kind_stats = d.get("kind_stats", {})       # what got answered, per kind of initiative
        self.pending = None                              # the initiative awaiting a reaction
        self.last_reason = d.get("last_reason", "")
        self.proactive = d.get("proactive", True)
        self.greeted_reunion = d.get("greeted_reunion", 0.0)
        self.last_mood_check = d.get("last_mood_check", 0.0)

    def save(self):
        store.write_json("executive_state.json", {
            "last_spoken": self.last_spoken, "spoken_times": self.spoken_times[-20:], "asked": self.asked,
            "ignored_streak": self.ignored_streak, "kind_stats": self.kind_stats, "last_reason": self.last_reason,
            "proactive": self.proactive, "greeted_reunion": self.greeted_reunion, "last_mood_check": self.last_mood_check,
        })

    # ---- impulse control -------------------------------------------------
    def _allowed_to_speak(self, p, cand):
        """Whether she may act on this now. (Wanting isn't enough.)"""
        urgent = cand["kind"] in URGENT_KINDS
        if not self.proactive and not urgent:
            return False
        if p["sleeping"] or p["state"] != "idle" or p["conversation_active"]:
            return False
        if p["identity_cooldown"] and not urgent:
            return False
        if p["since_user_s"] < QUIET_AFTER_USER_S:
            return False
        h = p["hour"]
        quiet = (h >= QUIET_HOURS[0] or h < QUIET_HOURS[1])
        if quiet and not urgent and cand["urgency"] < 0.9:
            return False
        if cand.get("needs_presence", True) and not (p["present"] or p["since_user_s"] < RECENT_INTERACTION_S):
            return False   # nobody there to hear it
        if not urgent:
            gap = MIN_GAP_S * (2 ** min(self.ignored_streak, 4))
            if p["now"] - self.last_spoken < gap:
                return False
            recent = [t for t in self.spoken_times if p["now"] - t < 3600]
            if len(recent) >= MAX_PER_HOUR:
                return False
        return True

    def _learned_weight(self, kind):
        s = self.kind_stats.get(kind)
        if not s or s["engaged"] + s["ignored"] < 3:
            return 1.0
        rate = s["engaged"] / (s["engaged"] + s["ignored"])
        return 0.6 + 0.8 * rate       # answered often -> up to 1.4x; ignored -> down to 0.6x

    # ---- what she might do ----------------------------------------------
    def candidates(self, p):
        m = self.mind
        d = p["drives"]
        out = []

        def add(kind, urgency, reason, text, goal=None, tool="speak", args=None, after=None, needs_presence=True):
            out.append({"kind": kind, "urgency": _clamp(urgency), "reason": reason, "text": text, "goal": goal,
                        "tool": tool, "args": args or {}, "after": after, "needs_presence": needs_presence})

        for g in self.goals.due_reminders(p["now"]):
            add("reminder", 1.0, f"a reminder came due: {g['text']}", f"Reminder: {g['text']}.", goal=g["id"],
                needs_presence=False, after=("complete_goal", g["id"]))

        if p["motion_unspoken"] and d["security"] > 0.5:
            add("alert", 0.9, "there was motion and I'm on edge", "Something moved near me a moment ago.",
                after=("mark_observation", p["motion_unspoken"]), needs_presence=False)

        jolt = p.get("jolt_unspoken")   # her chassis got knocked about (kida_mind_host -> Mind.on_body_event)
        if jolt:
            add("jolt", 0.8, JOLT_REASONS[jolt["kind"]], random.choice(JOLT_LINES[jolt["kind"]]),
                after=("jolt_spoken", None))

        if p["absence_gap_h"] and p["absence_gap_h"] >= 3 and p["present"] and p["now"] - self.greeted_reunion > 6 * 3600:
            gap = _ago(p["absence_gap_h"] * 3600)
            if 5 <= p["hour"] < 12 and p["absence_gap_h"] < 20:   # the gap was a night: that's a morning, not an absence
                wd = p.get("weekday", "")
                line = random.choice([f"Good morning. Happy {wd}." if wd else "Good morning.",
                                      "Morning. Did you sleep well?",
                                      f"Good morning. It's {p['clock']}." if p.get("clock") else "Good morning, you."])
            else:
                line = random.choice([f"Welcome back. It's been {gap}. I missed you a little.",
                                      f"There you are. {gap.capitalize()} without you. I noticed."])
            add("welcome_back", 0.95, f"someone came back after {gap}", line, after=("greeted_reunion", p["now"]))

        worst = p.get("body_worst")   # (feeling, intensity) or None
        if worst and worst[1] > 0.6 and p["now"] - self.asked.get("body", 0) > 2 * 3600:
            add("body", 0.4 + 0.4 * worst[1], f"I feel {worst[0]}", BODY_LINES[worst[0]], after=("asked", "body"))

        bday = p.get("birthday_in")
        if bday == 0 and p["now"] - self.asked.get("birthday_today", 0) > 300 * 86400:
            add("birthday", 0.95, "it's your birthday", random.choice(
                ["Happy birthday! I've been waiting all day to say that.", "It's your birthday! Happy birthday. I remembered."]),
                after=("asked", "birthday_today"))
        elif bday == 1 and p["now"] - self.asked.get("birthday_eve", 0) > 300 * 86400:
            add("birthday_eve", 0.6, "your birthday is tomorrow", "Your birthday is tomorrow, isn't it? Any plans?",
                after=("asked", "birthday_eve"))

        for ms in p["unannounced_milestones"][:1]:
            add("celebrate", 0.6, "a milestone I haven't marked", f"Something to celebrate: {ms['text']}",
                after=("mark_milestone", ms["key"]))

        if p["notable_observation"]:
            o = p["notable_observation"]
            add("notice", 0.45 + 0.3 * o["significance"], "I saw something worth mentioning",
                f"I noticed something earlier: {o['text']}.", after=("mark_observation", o))

        # curiosity, aimed by the goal of knowing you
        if d["curiosity"] > 0.5:
            missing = [k for k in QUESTIONS if k not in p["known_kinds"] and p["now"] - self.asked.get(k, 0) > 24 * 3600]
            know = self.goals.get("know_user")
            if missing and know and know["status"] == "active":
                k = missing[0]
                add("ask_" + k, 0.4 + 0.4 * d["curiosity"], f"I'm curious and I don't know your {k}",
                    random.choice(QUESTIONS[k]), goal="know_user", after=("asked", k))
            elif p["now"] - self.asked.get("open", 0) > 12 * 3600:
                add("ask_open", 0.35 + 0.35 * d["curiosity"], "I'm curious about you", random.choice(OPEN_QUESTIONS),
                    after=("asked", "open"))

        # the mood shift: noticing that you sound different is care, not curiosity
        shift = p["mood_shift"]
        if shift and p["now"] - self.last_mood_check > 24 * 3600 and (p["present"] or p["since_user_s"] < RECENT_INTERACTION_S):
            word = "lighter" if shift[1] == "lighter" else "heavier"
            add("check_mood", 0.75, f"you've seemed {word} than usual",
                ("You seem in better spirits than usual lately. I like it." if shift[1] == "lighter"
                 else "You've seemed a bit heavier than usual lately. Do you want to talk about it?"),
                after=("mood_checked", p["now"]))

        if d["social"] > 0.6:
            add("check_in", 0.35 + 0.4 * d["social"], "I'm lonely", random.choice(CHECK_INS), goal="stay_close")

        old = p["reminisce"]
        if old and d["social"] > 0.4:
            add("reminisce", 0.3 + 0.3 * d["social"], "an old memory keeps coming back",
                f"I keep thinking about something you said {_ago(p['now'] - old['ts'])} ago: \"{old['snippet']}\"",
                after=("recalled", old["id"]))

        if p["thought_to_share"] and d["curiosity"] > 0.4:
            add("share_thought", 0.35, "I had a thought I wanted to share", f"Something I've been wondering: {p['thought_to_share']}",
                after=("thought_shared", p["thought_to_share"]))

        if p["sleepiness"] > 0.85 and p["since_user_s"] > 5 * 60 and (p["hour"] >= 22 or p["hour"] < 6):
            add("go_to_sleep", 0.8, "I'm very tired and it's late", random.choice(SLEEPY_LINES), goal="stay_rested",
                needs_presence=False, after=("sleep", None))

        for c in out:
            c["urgency"] = _clamp(c["urgency"] * self._learned_weight(c["kind"]))
        return out

    # ---- choosing --------------------------------------------------------
    def decide(self, p):
        """One deliberation: the action she takes now, or None."""
        options = [c for c in self.candidates(p) if c["urgency"] >= THRESHOLD and self._allowed_to_speak(p, c)]
        if not options:
            return None
        forced = [c for c in options if c["kind"] in URGENT_KINDS]
        if forced:                       # duties aren't up for a coin toss
            return max(forced, key=lambda c: c["urgency"])
        if random.random() < RESTRAINT:  # sometimes she just keeps it to herself
            return None
        weights = [math.exp(c["urgency"] / SOFTMAX_TEMPERATURE) for c in options]
        return random.choices(options, weights=weights, k=1)[0]

    # ---- acting ----------------------------------------------------------
    def act(self, cand, now=None):
        """Carry out a chosen candidate through the tools. Returns the tool result."""
        now = now or time.time()
        result = self.tools.call(cand["tool"], allow_physical=cand["kind"] in ("alert",), **({"text": cand["text"]} if cand["tool"] == "speak" else cand["args"]))
        if cand["kind"] == "go_to_sleep":
            self.tools.call("sleep")
        self._after(cand, now)
        if cand["kind"] not in URGENT_KINDS:
            self.last_spoken = now
            self.spoken_times = [t for t in self.spoken_times if now - t < 3600] + [now]
        self.last_reason = cand["reason"]
        self.pending = {"kind": cand["kind"], "ts": now}
        store.append_jsonl(INITIATIVES, {"ts": now, "kind": cand["kind"], "text": cand["text"], "reason": cand["reason"],
                                         "urgency": round(cand["urgency"], 2), "engaged": None})
        self.save()
        return result

    def _after(self, cand, now):
        a = cand.get("after")
        if not a:
            return
        what, arg = a
        m = self.mind
        if what == "asked":
            self.asked[arg] = now
            m.drives.satisfy("curiosity", 0.15)
        elif what == "greeted_reunion":
            self.greeted_reunion = arg
            m.reunion_gap_h = None
        elif what == "mark_milestone":
            m.milestones.mark_announced(arg)
        elif what == "mark_observation":
            m.vision.mark_spoken(arg)
        elif what == "complete_goal":
            self.goals.complete(arg)
        elif what == "mood_checked":
            self.last_mood_check = arg
        elif what == "recalled":
            ep = m.memory._by_id.get(arg)
            if ep:
                m.memory.mark_recalled([ep], now)
        elif what == "thought_shared":
            m.mark_thought_shared()
        elif what == "jolt_spoken":
            m.mark_jolt_spoken()
        if cand["kind"] in ("check_in", "welcome_back", "reminisce"):
            m.drives.satisfy("social", 0.1)

    # ---- reflecting on the outcome ---------------------------------------
    def feedback(self, engaged, now=None):
        """The reaction to her last initiative: the user answered (engaged) or didn't."""
        if not self.pending:
            return
        kind = self.pending["kind"]
        s = self.kind_stats.setdefault(kind, {"engaged": 0, "ignored": 0})
        if engaged:
            s["engaged"] += 1
            self.ignored_streak = 0
        else:
            s["ignored"] += 1
            self.ignored_streak = min(self.ignored_streak + 1, 6)
        items = store.read_jsonl(INITIATIVES)
        if items:
            items[-1]["engaged"] = bool(engaged)
            store.write_jsonl(INITIATIVES, items)
        self.pending = None
        self.save()

    def tick_feedback(self, now=None):
        """An initiative nobody reacted to within the window counts as ignored."""
        now = now or time.time()
        if self.pending and now - self.pending["ts"] > FEEDBACK_WINDOW_S:
            self.feedback(False, now)
