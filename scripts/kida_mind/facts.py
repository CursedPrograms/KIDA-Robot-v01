"""
facts.py - durable facts about the person she lives with (ported from DREAM's
dream_memory.py).

memories/memories.txt     one line per fact learned in conversation:
                              [2026-09-21 14:05] (name) Human's name is Sam.
memories/mymilestones.txt  the first time each *kind* of fact (name, pet, home,
                              job, birthday) was learned.

Paths follow store.LEGACY_DIR, so the self-test's scratch folder keeps its
fake facts away from the real ones.
"""

import os
import re
import time
from datetime import datetime

from . import store

MAX_MEMORIES_IN_PROMPT = 6

# Kinds where only the latest fact matters (a new name replaces the old one).
# Anything else (pets) keeps every distinct fact.
SINGLE_VALUE_KINDS = {"name", "home", "job", "birthday"}

_TIME_FORMAT = "%Y-%m-%d %H:%M"
_LINE = re.compile(r"\[(.*?)\]\s*\((\w+)\)\s*(.*)")

_MEMORY_PATTERNS = [
    ("name",     re.compile(r"\bmy name is ([A-Z][a-zA-Z'-]{1,20})\b", re.I)),
    ("pet",      re.compile(r"\bi (?:have|own) an? (dog|cat|bird|fish|rabbit|hamster)(?: named ([A-Z][a-zA-Z'-]{1,20}))?\b", re.I)),
    ("home",     re.compile(r"\bi live in ([A-Za-z][A-Za-z\s]{1,30}?)[.,!]?$", re.I)),
    ("job",      re.compile(r"\bi work as an? ([A-Za-z][A-Za-z\s]{1,30}?)[.,!]?$", re.I)),
    ("birthday", re.compile(r"\bmy birthday is ([A-Za-z0-9,\s]{3,30}?)[.,!]?$", re.I)),
]


def memories_path():
    return str(store.LEGACY_DIR / "memories.txt")


def milestones_path():
    return str(store.LEGACY_DIR / "mymilestones.txt")


def extract_memories(user_text: str):
    """Pull simple durable facts (name, pet, home, job, birthday) out of user_text.
    Returns [(kind, sentence), ...]."""
    found = []
    m = _MEMORY_PATTERNS[0][1].search(user_text)
    if m:
        found.append(("name", f"Human's name is {m.group(1)}."))
    m = _MEMORY_PATTERNS[1][1].search(user_text)
    if m:
        pet, pname = m.group(1).lower(), m.group(2)
        found.append(("pet", f"Human has a {pet}" + (f" named {pname}." if pname else ".")))
    m = _MEMORY_PATTERNS[2][1].search(user_text)
    if m:
        found.append(("home", f"Human lives in {m.group(1).strip()}."))
    m = _MEMORY_PATTERNS[3][1].search(user_text)
    if m:
        found.append(("job", f"Human works as a {m.group(1).strip()}."))
    m = _MEMORY_PATTERNS[4][1].search(user_text)
    if m:
        found.append(("birthday", f"Human's birthday is {m.group(1).strip()}."))
    return found


def read_memories():
    """[(datetime, kind, text), ...] oldest first; lines that don't parse are skipped."""
    entries = []
    path = memories_path()
    if not os.path.exists(path):
        return entries
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = _LINE.match(line.strip())
            if not m:
                continue
            try:
                when = datetime.strptime(m.group(1), _TIME_FORMAT)
            except ValueError:
                continue
            entries.append((when, m.group(2), m.group(3)))
    return entries


def _append_line(path, line):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def remember(kind: str, text: str):
    """Save a fact. Returns "milestone" if this is the first fact of its kind
    (also logged to mymilestones.txt), "memory" if it's a new fact, or None if
    it was already known (so repeating yourself doesn't pile up duplicates)."""
    entries = read_memories()
    if any(k == kind and t.lower() == text.lower() for _, k, t in entries):
        return None

    ts = time.strftime(_TIME_FORMAT)
    _append_line(memories_path(), f"[{ts}] ({kind}) {text}")
    if any(k == kind for _, k, _ in entries):
        return "memory"
    _append_line(milestones_path(), f"[{ts}] {text}")
    return "milestone"


def _age(when: datetime, now: datetime | None = None) -> str:
    seconds = max(0, int(((now or datetime.now()) - when).total_seconds()))
    if seconds < 3600:
        minutes = seconds // 60
        return "just now" if minutes < 1 else f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    if seconds < 86400:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = seconds // 86400
    if days == 1:
        return "yesterday"
    if days < 30:
        return f"{days} days ago"
    return "on " + when.strftime("%Y-%m-%d")


def recent_memories(limit=MAX_MEMORIES_IN_PROMPT):
    """The facts worth putting in the prompt, oldest first, each with how long
    ago it was learned: latest-only for single-value kinds, every distinct fact
    otherwise, capped at the `limit` most recent."""
    kept = {}
    for when, kind, text in read_memories():
        key = kind if kind in SINGLE_VALUE_KINDS else (kind, text.lower())
        kept.pop(key, None)  # re-insert so dict order tracks recency
        kept[key] = (when, text)
    latest = sorted(kept.values(), key=lambda e: e[0])[-limit:]
    now = datetime.now()
    return [f"{text} (learned {_age(when, now)})" for when, text in latest]


def memory_prompt_block(limit=MAX_MEMORIES_IN_PROMPT) -> str:
    """Text to append to the system prompt, or "" if nothing is remembered."""
    lines = recent_memories(limit)
    if not lines:
        return ""
    return "\n\nThings you remember about the human:\n" + "\n".join(f"- {m}" for m in lines)


def forget_matching(phrase):
    """Drop every fact line mentioning `phrase`. Returns how many."""
    path, p = memories_path(), phrase.lower()
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return 0
    kept = [l for l in lines if p not in l.lower()]
    if len(kept) != len(lines):
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(kept)
    return len(lines) - len(kept)


def forget_all():
    for path in (memories_path(), milestones_path()):
        try:
            open(path, "w").close()
        except OSError:
            pass
