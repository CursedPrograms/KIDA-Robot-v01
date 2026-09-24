"""
store.py - where the mind keeps itself: small JSON / JSON-lines files under
memories/mind/. Writes are atomic (temp file + rename) so a crash or a second
process can't leave a half-written file.
"""

import json
import os
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # repo root (scripts/kida_mind/store.py)
_dir = ROOT / "memories" / "mind"
LEGACY_DIR = ROOT / "memories"   # memories.txt, mymilestones.txt: the human-readable files
_lock = threading.RLock()


def set_dir(path):
    """Point the mind at another folder (the self-test uses a temp one). The
    human-readable text files move with it, so tests never touch the real ones."""
    global _dir, LEGACY_DIR
    _dir = Path(path)
    LEGACY_DIR = _dir / "legacy"


def mind_dir() -> Path:
    _dir.mkdir(parents=True, exist_ok=True)
    return _dir


def path(name: str) -> Path:
    return mind_dir() / name


def read_json(name, default=None):
    with _lock:
        try:
            with open(path(name), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return default


def write_json(name, obj):
    with _lock:
        p = path(name)
        tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)
        os.replace(tmp, p)


def append_jsonl(name, obj):
    with _lock:
        with open(path(name), "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def read_jsonl(name):
    items = []
    with _lock:
        try:
            with open(path(name), encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        items.append(json.loads(line))
                    except ValueError:
                        pass  # a torn or hand-edited line: skip it
        except OSError:
            pass
    return items


def write_jsonl(name, items):
    with _lock:
        p = path(name)
        tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            for it in items:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
        os.replace(tmp, p)


def remove(name):
    with _lock:
        try:
            os.remove(path(name))
        except OSError:
            pass
