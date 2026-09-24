"""
milestones.py - the moments that mark her life.

Milestones go into the same memories/mymilestones.txt facts.py already
writes (first time she learns a name, a pet, and so on), plus richer ones from
the mind: a first conversation, the hundredth, her first night
of sleep, a first reunion after a long absence, a week and a month together.
Each is announced once, in her own time.
"""

import time

from . import store

FILE = "milestones.jsonl"


class Milestones:
    def __init__(self):
        self.items = store.read_jsonl(FILE)
        self.have = {m["key"] for m in self.items}

    def award(self, key, text, now=None):
        """Record a milestone once. Returns it if it's new."""
        if key in self.have:
            return None
        now = now or time.time()
        item = {"key": key, "ts": now, "text": text, "announced": False}
        self.items.append(item)
        self.have.add(key)
        store.append_jsonl(FILE, item)
        try:
            legacy = store.LEGACY_DIR / "mymilestones.txt"
            legacy.parent.mkdir(parents=True, exist_ok=True)
            with open(legacy, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M', time.localtime(now))}] {text}\n")
        except OSError:
            pass
        return item

    def unannounced(self):
        return [m for m in self.items if not m.get("announced")]

    def mark_announced(self, key):
        for m in self.items:
            if m["key"] == key:
                m["announced"] = True
        store.write_jsonl(FILE, self.items)

    def check(self, *, conversations=0, nights=0, first_seen=None, now=None):
        """Award any milestone the counts have reached. Returns the new ones."""
        now = now or time.time()
        new = []
        table = [
            (conversations >= 1, "first_conversation", "Our first conversation."),
            (conversations >= 10, "conversations_10", "We've had ten conversations."),
            (conversations >= 50, "conversations_50", "Fifty conversations together."),
            (conversations >= 100, "conversations_100", "A hundred conversations. That's a lot of shared history."),
            (nights >= 1, "first_night", "My first full night of sleep."),
        ]
        if first_seen:
            days = (now - first_seen) / 86400.0
            table += [(days >= 7, "one_week", "One week together."), (days >= 30, "one_month", "One month together.")]
        for reached, key, text in table:
            if reached:
                item = self.award(key, text, now)
                if item:
                    new.append(item)
        return new
