#!/usr/bin/env python3
"""
kida_drive_mind.py — MIND mode (mode 9): an LLM drives her, stop-look-think-move.

Not her inner life (kida_mind_host.py: moods, dreams, chatting); this is the fleet's
MIND mode (mind.py, the same file in every robot's controller): she stands still, the
mind looks at what she senses, thinks out loud, says something, makes one short move,
and remembers it.

Where the mind runs is an option: config.json Config/Mind/Where (options.py, her web
page /options, or the PC controller's Options button):
    "auto"  (the default) a PC controller that can think (x86, 8 GB+ RAM, GTX 1050 or
            better: mind.can_think()) drives her while it's checked in; with none, her
            own Pi does, with SelfModel on her own Ollama (small, so simple). A PC that
            checks in takes over; one that goes quiet hands her back to herself.
    "pc"    only a PC, as the rest of the fleet: no PC checked in, no MIND mode.
    "self"  always her own Pi, even with a PC connected.
    "off"   no MIND mode.
SelfModel ("qwen2.5:0.5b", the one her voice chat uses) and SelfThink (false: only
qwen3-type models think) are her own mind's; Goal is what either mind is told to do.

The fleet's contract (fleet TODO section 10), as NORA / MILA / WHIP do it:
    /unlock?pw=&ctl=1     a PC mind host unlocks and checks in
    /status?ctl=1         ...and keeps checking in (every < 5 s); /status adds mindHost,
                          mindSteps, blocked, mindBrain ("pc" / "self" / null)
    /mind?act=&steps=1-4  the PC's moves: only from it, only in MIND, only while the PC
                          is her brain; fwd with a wall within WALL_CM is refused
Reflexes stay on: the motor lock (arduino.send_command), the wall stop, the bump switch.
"""

import threading
import time

import kida_config
import state
from state import DriveMode

MIND_DEFAULTS = {
    "Where":     "auto",
    "SelfModel": "qwen2.5:0.5b",
    "SelfThink": False,
    "Goal":      "explore the room, say what you notice, and don't bump into anything",
}
WHERE = ("auto", "pc", "self", "off")

HOST_TTL_S = 5.0     # a PC mind host silent this long is gone
STEP_S     = 0.4     # one step of driving
WALL_CM    = 20      # never forward into anything this close
PWM        = 150
OLLAMA     = "http://localhost:11434"

NAME = "KIDA01"
# --- persona start ---
PERSONA = ("KIDA-01, the bigger KIDA, a tracked robot with two eyes: a night camera on her left "
           "and an AI camera on her right, which see together in the middle. Warm, nosy and chatty, "
           "she narrates what she finds like a nature documentary, is very proud of seeing in stereo, "
           "teases her little sister KIDA-00, and keeps one eye on her battery.")
VOICE = ("Microsoft Zira Desktop", 1, "medium")   # on the PC; on herself she speaks with Piper
# --- persona end ---
MOVES = {"fwd": "drive forward a little", "bwd": "drive backward a little",
         "left": "turn left on the spot", "right": "turn right on the spot"}
SAFETY = ("she won't drive forward into anything within 20 cm, stops if she bumps something, "
          "and her motor lock stops her completely")

_host = {"ip": None, "seen": 0.0}
_drive = {"steps": 0, "blocked": False}
_lock = threading.Lock()
_self_mind = None
_supervisor = None


def settings() -> dict:
    s = kida_config.section("Mind", MIND_DEFAULTS)
    if str(s.get("Where", "")).lower() not in WHERE:
        s["Where"] = "auto"
    s["Where"] = str(s["Where"]).lower()
    s["SelfThink"] = bool(s.get("SelfThink"))
    return s


# ── the PC mind host ───────────────────────────────────────────────────────
def check_in(ip: str) -> None:
    _host.update(ip=ip, seen=time.time())


def host_ip():
    return _host["ip"] if _host["ip"] and time.time() - _host["seen"] < HOST_TTL_S else None


def brain():
    """Who would drive her in MIND mode right now: "pc", "self" or None."""
    where = settings()["Where"]
    pc = host_ip() is not None
    if where == "off":
        return None
    if where == "self":
        return "self"
    if pc:
        return "pc"
    return "self" if where == "auto" else None


def in_mind() -> bool:
    return state.drive_mode == DriveMode.MIND


def request_mode() -> bool:
    """/mode?m=mind, mode_9, key 9: into MIND mode if a mind can drive her."""
    if brain() is None:
        print("🧠 MIND mode: no mind to drive her (config.json Mind/Where, or no PC checked in)")
        return False
    import mode_manager
    mode_manager.set_mode(DriveMode.MIND)
    return True


# ── her body ───────────────────────────────────────────────────────────────
def _motors(left: int, right: int) -> None:
    from arduino import set_left_motor, set_right_motor
    set_left_motor(left)
    set_right_motor(right)


def act(move: str, steps: int) -> dict:
    """One move, blocking: steps x STEP_S of driving. Says how it went."""
    from haptics import closest_cm
    from sensor_assist import _parse_int
    steps = max(1, min(4, int(steps)))
    if move == "stop" or not in_mind():
        _motors(0, 0)
        return {"ok": True}
    if move not in MOVES:
        return {"ok": False, "error": f"no move {move}"}
    if state.motor_lock:
        return {"ok": False, "locked": True}
    d = closest_cm()
    if move == "fwd" and d is not None and d < WALL_CM:
        _drive["blocked"] = True
        return {"ok": False, "blocked": True, "front_cm": d}
    left, right = {"fwd": (PWM, PWM), "bwd": (-PWM, -PWM),
                   "left": (-PWM, PWM), "right": (PWM, -PWM)}[move]
    _drive.update(steps=steps, blocked=False)
    end = time.monotonic() + steps * STEP_S
    why = ""
    try:
        while time.monotonic() < end and in_mind():
            if move == "fwd":
                d = closest_cm()
                if d is not None and d < WALL_CM:
                    _drive["blocked"], why = True, f"stopped at a wall ({d} cm)"
                    break
            if _parse_int(state.ballSwitchValue) == 1 and move in ("fwd", "bwd"):
                why = "bumped something"
                break
            _motors(left, right)
            _drive["steps"] = max(1, round((end - time.monotonic()) / STEP_S))
            time.sleep(0.05)
    finally:
        _motors(0, 0)
        _drive["steps"] = 0
    out = {"ok": True, "front_cm": closest_cm()}
    if why:
        out["stopped"] = why
    return out


def look() -> dict:
    """What she senses: distances, what her cameras' detectors see, battery, tilt."""
    from haptics import closest_cm, level
    from sensor_assist import _parse_int
    senses = {"closest_cm": closest_cm()}
    for key, attr in (("front_ultrasonic_cm", "ultrasonic0Value"), ("servo_ultrasonic_cm", "ultrasonic1Value"),
                      ("laser_mm", "laserValue")):
        v = _parse_int(getattr(state, attr, None))
        if v is not None and v > 0:
            senses[key] = v
    cams = kida_config.cameras()
    night, ai = cams["NightCamSide"], ("right" if cams["NightCamSide"] == "left" else "left")
    seen = {}
    for side, attr in ((night, "detection_boxes"), (ai, "cam1_detection_boxes")):
        for b in list(getattr(state, attr, []) or []):
            cx = (b["box"][0] + b["box"][2]) / 2
            where = "left" if cx < 0.4 else "right" if cx > 0.6 else "ahead"
            seen.setdefault(f"{b['label']} ({side} camera, {where})", round(b.get("conf", 0), 2))
    senses["cameras_see"] = list(seen) or "nothing they recognise"
    bat = getattr(state, "bat_pct", None)
    if bat:
        senses["battery_pct"] = round(bat)
    try:
        _, _, reason = level()
        if reason:
            senses["body"] = reason
    except Exception:
        pass
    senses["last_forward_blocked"] = _drive["blocked"]
    return senses


# ── the PC's moves ─────────────────────────────────────────────────────────
def pc_move(ip: str, move: str, steps) -> tuple:
    """/mind?act=&steps=: returns (json, http status) at once; the move runs on its own thread."""
    if ip != host_ip():
        return {"ok": False, "error": "only her mind host"}, 403
    if not in_mind() or brain() != "pc":
        return {"ok": False, "error": "not in MIND mode with the PC driving"}, 409
    try:
        steps = int(steps or 1)
    except ValueError:
        steps = 1
    if move == "stop":
        act("stop", 1)
        return {"ok": True}, 200
    from haptics import closest_cm
    d = closest_cm()
    if move == "fwd" and d is not None and d < WALL_CM:
        _drive["blocked"] = True
        return {"ok": False, "blocked": True, "front_cm": d}, 200
    if move not in MOVES:
        return {"ok": False, "error": f"no move {move}"}, 400
    if _drive["steps"]:
        return {"ok": False, "error": "still moving"}, 409
    _drive["steps"] = max(1, min(4, steps))
    threading.Thread(target=act, args=(move, steps), daemon=True, name="mind-move").start()
    return {"ok": True}, 200


def status_fields() -> dict:
    m = _self_mind
    out = {"mindHost": 1 if host_ip() else 0, "mindSteps": _drive["steps"], "blocked": _drive["blocked"],
           "mindBrain": brain(), "mindWhere": settings()["Where"], "mindAvailable": brain() is not None,
           "mindGoal": settings()["Goal"], "cameras": {"NightCamSide": kida_config.cameras()["NightCamSide"]}}
    if m is not None and m.on:   # her own mind's thoughts, for the HUD / PC / page
        out["mindSelf"] = {"state": m.state, "thinking": m.thinking[-1200:], "said": m.said,
                           "last": m.last, "error": m.error}
    return out


# ── her own mind (on the Pi) ───────────────────────────────────────────────
def _robot_say(text: str) -> bool:
    try:
        import kida_chat_wakeword
        kida_chat_wakeword.say(text)
    except Exception as e:
        print(f"🧠 (can't say it: {e}) {text}")
    return True   # never the PC's Windows voice: there's none on the Pi


def _make_self_mind():
    import mind
    s = settings()
    return mind.Mind(NAME, PERSONA, MOVES, look, act, robot_say=_robot_say, voice=VOICE[0],
                     rate=VOICE[1], pitch=VOICE[2], safety=SAFETY,
                     model=s["SelfModel"], think=s["SelfThink"], ollama=OLLAMA)


def _supervise() -> None:
    """While she's in MIND mode: her own mind runs when it's hers to run, a PC
    takes over when it checks in, and with no mind at all she leaves MIND."""
    global _self_mind
    while in_mind():
        b = brain()
        mine = _self_mind is not None and _self_mind.on
        # a stopped mind's loop can still be finishing a thought: wait for it, or two would run
        winding_down = (_self_mind is not None and not mine and _self_mind._thread is not None
                        and _self_mind._thread.is_alive())
        if b == "self" and not mine and not winding_down:
            try:
                _self_mind = _self_mind or _make_self_mind()
                _self_mind.start(goal=settings()["Goal"])
                print(f"🧠 MIND: thinking for herself ({settings()['SelfModel']} on her Pi)")
            except Exception as e:
                print(f"⚠️  MIND: her own mind won't start ({e})")
                break
        elif b != "self" and mine:
            _self_mind.stop()
            print("🧠 MIND: the PC's mind is driving her" if b == "pc" else "🧠 MIND: no mind left")
        if b is None:
            break
        time.sleep(0.5)
    if _self_mind is not None and _self_mind.on:
        _self_mind.stop()
    _motors(0, 0)
    if in_mind():   # nobody to drive her: back to the keyboard
        import mode_manager
        mode_manager.set_mode(DriveMode.KEYBOARD)


def on_mode_change(new_mode: DriveMode) -> None:
    global _supervisor
    if new_mode == DriveMode.MIND:
        if _supervisor is None or not _supervisor.is_alive():
            _supervisor = threading.Thread(target=_supervise, daemon=True, name="mind-mode")
            _supervisor.start()
    elif _self_mind is not None and _self_mind.on:
        _self_mind.stop()
