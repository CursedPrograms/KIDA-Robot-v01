"""
kida_mind - KIDA's inner life.

Ported from DREAM's dream_mind (same author, same design) and adapted to a
robot body: moods, needs, episodic memory that fades and strengthens, a model
of the person she lives with, sleep that consolidates memory (no dreams -
that's DREAM's; too costly on a Pi), a running self-narrative, and initiative (she sometimes speaks first).

Her body here is the robot: the Pi she runs on, her battery, her cameras,
her range sensors, and what happens to her chassis (bumps, tipping, being
driven around). kida_mind_host.py (one folder up) wires all of that in.

None of this makes her conscious; it makes her behave as though she has an
inner state, because she does have one - it's just numbers, files and prompts.
See mind.py for the entry point: get_mind().
"""


def __getattr__(name):
    # Imported lazily so `import kida_mind.affect` etc. stay light.
    if name in ("Mind", "get_mind"):
        from . import mind
        return getattr(mind, name)
    raise AttributeError(name)
