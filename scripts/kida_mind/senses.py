"""
senses.py - when she is, and what her body (the robot) feels like.

  Clock      the time, the date, the day of the week, the part of the day, the
             season. The language model has no idea what time it is; this does.
  Calendar   your birthday (if she knows it), weekends, how long she's known you.
  Body       interoception: the Pi she runs on, read through psutil, and her
             battery, read by the INA219 power monitor (state.bat_pct). A busy
             processor feels like strain, full memory like fog, a nearly full
             disk like being cramped, heat like discomfort, a draining battery
             like running low. How long the Pi has been on, and how long she
             has been awake. (Bumps, tipping and being driven are events, not
             levels - kida_mind_host.py feeds those to the mind directly.)

Reading the body is cheap (no waiting on the CPU sample), cached for a few
seconds, and never raises: a machine that can't report something simply
doesn't feel it.
"""

import re
import time

try:
    import psutil
except Exception:          # the mind still works without it, just without a body
    psutil = None

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]
MONTH_ABBR = {m[:3]: i + 1 for i, m in enumerate(MONTHS)}

STRAIN_CPU = 85.0      # percent, sustained
FOG_RAM = 90.0
CRAMPED_DISK = 95.0
HOT_C = 80.0          # the Pi 5 starts throttling around here
LOW_BATTERY = 20.0
BODY_CACHE_S = 5.0
STRAIN_SMOOTHING = 0.3  # how quickly sustained load registers (a spike isn't strain)


# ---------------------------------------------------------------- clock

def part_of_day(hour):
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 21:
        return "evening"
    return "night"


def season(month, southern=False):
    s = ["winter", "winter", "spring", "spring", "spring", "summer", "summer", "summer", "autumn", "autumn", "autumn", "winter"][month - 1]
    if southern:
        s = {"winter": "summer", "summer": "winter", "spring": "autumn", "autumn": "spring"}[s]
    return s


def clock_time(t):
    """'9:05 pm' - the way people say it."""
    h = t.tm_hour % 12 or 12
    return f"{h}:{t.tm_min:02d} {'am' if t.tm_hour < 12 else 'pm'}"


def date_words(t):
    """'Tuesday, 23 September 2026'"""
    return f"{time.strftime('%A', t)}, {t.tm_mday} {time.strftime('%B', t)} {t.tm_year}"


def clock(now=None, southern=False):
    now = now or time.time()
    t = time.localtime(now)
    hour = t.tm_hour + t.tm_min / 60.0
    return {
        "ts": now, "time": clock_time(t), "date": date_words(t), "weekday": time.strftime("%A", t),
        "hour": round(hour, 2), "part": part_of_day(hour), "season": season(t.tm_mon, southern),
        "weekend": t.tm_wday >= 5, "month": t.tm_mon, "day": t.tm_mday,
    }


def clock_line(now=None, southern=False):
    c = clock(now, southern)
    return f"It is {c['time']} on {c['date']} ({c['part']}, {c['season']})."


# ---------------------------------------------------------------- calendar

def parse_birthday(text):
    """'March 3rd', '3 March', 'the 3rd of march', '03/03' -> (month, day), or None.
    Numeric dates are read day/month unless that's impossible."""
    t = text.lower()
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?(?: of)? ([a-z]{3,9})\b", t) or None
    if m and m.group(2)[:3] in MONTH_ABBR:
        return _valid(MONTH_ABBR[m.group(2)[:3]], int(m.group(1)))
    m = re.search(r"\b([a-z]{3,9}) (?:the )?(\d{1,2})(?:st|nd|rd|th)?\b", t)
    if m and m.group(1)[:3] in MONTH_ABBR:
        return _valid(MONTH_ABBR[m.group(1)[:3]], int(m.group(2)))
    m = re.search(r"\b(\d{1,2})[/.-](\d{1,2})\b", t)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return _valid(b, a) or _valid(a, b)
    return None


def _valid(month, day):
    days = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return (month, day) if 1 <= month <= 12 and 1 <= day <= days[month - 1] else None


def days_until(month, day, now=None):
    """Days from today to the next (month, day); 0 means today."""
    now = now or time.time()
    t = time.localtime(now)
    today = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 12, 0, 0, 0, 0, -1))
    for year in (t.tm_year, t.tm_year + 1, t.tm_year + 2):   # +2 covers 29 February
        try:
            target = time.mktime((year, month, day, 12, 0, 0, 0, 0, -1))
        except (OverflowError, ValueError):
            continue
        if time.localtime(target).tm_mday != day:   # 29 Feb in a non-leap year rolls over
            continue
        if target >= today - 3600:
            return round((target - today) / 86400)
    return None


def known_birthday():
    """(month, day) of the user's birthday, if she's been told it."""
    try:
        from .facts import read_memories
        for _, kind, text in reversed(read_memories()):
            if kind == "birthday":
                return parse_birthday(text)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------- body

class Body:
    def __init__(self, reader=None):
        self._reader = reader or read_machine   # injectable, so tests can give her a fever
        self._cache, self._cache_ts = None, 0.0
        self.strain = 0.0                        # smoothed CPU load, 0..1
        self.awake_since = time.time()           # when this process started

    def read(self, now=None):
        now = now or time.time()
        if self._cache is None or now - self._cache_ts >= BODY_CACHE_S:
            try:
                self._cache = self._reader() or {}
            except Exception:
                self._cache = {}
            self._cache_ts = now
            cpu = self._cache.get("cpu_pct")
            if cpu is not None:
                self.strain += (cpu / 100.0 - self.strain) * STRAIN_SMOOTHING
        return self._cache

    def feelings(self, now=None):
        """What stands out about her body right now, as [(name, intensity 0..1)]."""
        r = self.read(now)
        out = []
        if self.strain * 100 >= STRAIN_CPU:
            out.append(("strained", min(1.0, (self.strain * 100 - STRAIN_CPU) / (100 - STRAIN_CPU) + 0.4)))
        if (r.get("ram_pct") or 0) >= FOG_RAM:
            out.append(("foggy", min(1.0, (r["ram_pct"] - FOG_RAM) / (100 - FOG_RAM) + 0.4)))
        if (r.get("disk_pct") or 0) >= CRAMPED_DISK:
            out.append(("cramped", 0.5))
        if (r.get("temp_c") or 0) >= HOT_C:
            out.append(("hot", min(1.0, (r["temp_c"] - HOT_C) / 15 + 0.4)))
        b = r.get("battery_pct")
        if b is not None and not r.get("plugged", True) and b <= LOW_BATTERY:
            out.append(("running low", min(1.0, (LOW_BATTERY - b) / LOW_BATTERY + 0.4)))
        return out

    def describe(self, now=None):
        """'strained and hot', or '' when she feels fine."""
        words = [n for n, _ in self.feelings(now)]
        return " and ".join(words) if len(words) <= 2 else ", ".join(words[:-1]) + " and " + words[-1]

    def discomfort(self, now=None):
        """How much her body bothers her (0..1)."""
        f = self.feelings(now)
        return max((i for _, i in f), default=0.0)

    def report(self, now=None):
        """A spoken answer to 'how's your body' / 'how are you running'."""
        r = self.read(now)
        if not r:
            return "I can't feel my body right now. My Pi isn't telling me anything."
        bits = []
        if r.get("cpu_pct") is not None:
            bits.append(f"my processor is at {r['cpu_pct']:.0f} percent")
        if r.get("ram_pct") is not None:
            bits.append(f"memory is {r['ram_pct']:.0f} percent full")
        if r.get("temp_c"):
            bits.append(f"I'm running at {r['temp_c']:.0f} degrees")
        if r.get("battery_pct") is not None:
            bits.append(f"battery at {r['battery_pct']:.0f} percent{'' if r.get('plugged') else ', unplugged'}")
        feel = self.describe(now)
        head = f"I feel {feel}." if feel else "I feel fine."
        up = r.get("boot_ts")
        tail = f" My Pi has been on for {duration_words((now or time.time()) - up)}." if up else ""
        said = ", ".join(bits)
        return f"{head} {said[:1].upper()}{said[1:]}.{tail}" if bits else head + tail

    def summary(self, now=None):
        r = self.read(now)
        return {**{k: r.get(k) for k in ("cpu_pct", "ram_pct", "disk_pct", "temp_c", "battery_pct", "plugged")},
                "strain": round(self.strain, 2), "feels": self.describe(now) or "fine",
                "awake_s": round((now or time.time()) - self.awake_since)}


def read_machine():
    if psutil is None:
        return {}
    r = {"cpu_pct": psutil.cpu_percent(interval=None), "ram_pct": psutil.virtual_memory().percent}
    try:
        import os
        r["disk_pct"] = psutil.disk_usage(os.path.abspath(os.sep)).percent
    except Exception:
        pass
    try:
        temps = psutil.sensors_temperatures()   # Linux only
        vals = [t.current for key in ("coretemp", "k10temp", "cpu_thermal", "acpitz") for t in temps.get(key, [])]
        if vals:
            r["temp_c"] = max(vals)
    except Exception:
        pass
    try:
        b = psutil.sensors_battery()
        if b is not None:
            r["battery_pct"], r["plugged"] = b.percent, bool(b.power_plugged)
    except Exception:
        pass
    try:   # KIDA's own battery: the INA219 reading ui.py keeps in state (0 until it has one)
        import state
        pct = float(getattr(state, "bat_pct", 0.0) or 0.0)
        if pct > 0:
            r["battery_pct"], r["plugged"] = pct, False
    except Exception:
        pass
    try:
        r["boot_ts"] = psutil.boot_time()
    except Exception:
        pass
    return r


def duration_words(seconds):
    m = int(max(0, seconds) / 60)
    if m < 2:
        return "a minute"
    if m < 60:
        return f"{m} minutes"
    h = m / 60
    if h < 36:
        return f"{h:.0f} hour{'s' if round(h) != 1 else ''}"
    d = h / 24
    return f"{d:.0f} day{'s' if round(d) != 1 else ''}"
