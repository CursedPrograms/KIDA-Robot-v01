"""
sleeping.py - what happens while she sleeps.

DREAM (where this mind comes from) dreams: every sleep cycle it writes a
story with the language model and paints it. On a Raspberry Pi that's a lot
of processing for something nobody sees, so KIDA doesn't dream. Sleep keeps
only the cheap, useful part, once per nap:

  consolidation  the day's memories are replayed - the important ones
                 strengthen, the trivial ones fade and are archived
  drift          her tastes and her philosophy wander a little
  taking stock   she notices patterns (what you keep talking about, when
                 you're usually around, whether you've seemed different)

Then she simply rests until something wakes her. Waking is instant: there's
nothing in progress to abandon.
"""

import threading
import time

from . import store

INSIGHTS = "insights.jsonl"


class Sleeper:
    def __init__(self, mind):
        self.mind = mind

    def run_session(self, stop: threading.Event, use_llm=False, **_ignored):
        """Sleep until `stop` is set (she was woken). Returns what happened."""
        m = self.mind
        report = {"started": time.time(), "cycles": 0, "consolidation": [], "insights": []}
        if not stop.is_set():
            report["consolidation"].append(m.memory.consolidate())
            m.opinions.drift()
            m.philosophy.drift()
            report["insights"] = self.take_stock()
            report["cycles"] = 1
        stop.wait()   # rest - costs nothing
        report["ended"] = time.time()
        return report

    def take_stock(self):
        """Patterns she notices about your days while consolidating."""
        m = self.mind
        notes = []
        topics = m.memory.topics(3)
        if topics:
            notes.append("We keep coming back to " + ", ".join(topics) + ".")
        hours = m.vision.presence_pattern()
        if hours:
            notes.append("You're usually around at " + ", ".join(f"{h}:00" for h in sorted(hours)) + ".")
        shift = m.memory.mood_shift()
        if shift:
            notes.append(f"You've seemed {shift[1]} than usual lately.")
        for n in notes:
            store.append_jsonl(INSIGHTS, {"ts": time.time(), "text": n})
        return notes
