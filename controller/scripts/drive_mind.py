# drive_mind.py — the PC controller's side of her MIND mode (scripts/kida_drive_mind.py)
#
# Only on a PC that can think (mind.can_think(): x86, 8 GB+ RAM, GTX 1050 or
# better). Then this signs in as her mind host (/unlock?pw=&ctl=1, her motor
# lock left alone), keeps checking in on /status?ctl=1 (remote_client.py), and
# when she's in MIND mode with the PC as her brain (config.json Mind/Where
# "auto" or "pc"), runs mind.py's Mind with her body over the network:
#
#   look   /status (distances, what her cameras' detectors see, battery) plus,
#          when Ollama has a vision model, both cameras' pictures through
#          mind.see(): the night cam is her left eye and the AI cam her right
#          (config.json Cameras), and what's in both is straight ahead
#   act    /mind?act=&steps=, then /status until mindSteps is 0
#   speak  mind.windows_wav() POSTed to /speak: her own speaker
#
# With Where "self" (or no PC) her own Pi thinks instead; status()["mindSelf"]
# carries those thoughts, and main.py shows them the same way.

import os
import threading
import time
from types import SimpleNamespace

import requests

import mind
import kida_drive_mind as robot   # the same persona / moves as on her (scripts/)

PIN = os.environ.get("KIDA_PIN", "1234")   # a safety catch, not security
MOVE_TIMEOUT_S = 6.0
LOOK_QUESTION = (
    "List the objects you can see in this picture, each with where it is in the picture and how big it "
    "looks. Answer JSON only: "
    '{"objects": [{"name": "...", "x": "left|centre|right", "size": "small|medium|large"}]}'
)


class DriveMind:
    def __init__(self, remote):
        self.remote = remote
        self.capable, self.why = False, "checking this PC..."
        self.mind = mind.Mind(robot.NAME, robot.PERSONA, robot.MOVES, self.look, self.act,
                              robot_say=self.robot_say, voice=robot.VOICE[0], rate=robot.VOICE[1],
                              pitch=robot.VOICE[2], safety=robot.SAFETY)
        threading.Thread(target=self._check, daemon=True).start()

    def _check(self):
        self.capable, self.why = mind.can_think()
        if not self.capable:
            print(f"🧠 MIND mode stays on her (or off): {self.why}")
            return
        self.remote.mind_host = True   # remote_client polls /status?ctl=1 from now on
        while self.remote._running:
            try:
                r = requests.get(f"{self.remote.base_url}/unlock", params={"pw": PIN, "ctl": "1"}, timeout=2)
                if r.ok:
                    print(f"🧠 This PC can drive her mind ({mind.CHOSEN_MODEL})")
                    return
                self.why = f"she said {r.status_code} to the PIN (KIDA_PIN)"
                return
            except requests.RequestException:
                time.sleep(3)   # not up yet

    # ── her body, over the network ──
    def _get(self, path, **kw):
        r = requests.get(f"{self.remote.base_url}{path}", timeout=kw.pop("timeout", 3), **kw)
        return r.json()

    def look(self):
        s = self._get("/status?ctl=1")
        senses = {k: s.get(k) for k in ("bat_pct", "blocked", "person") if s.get(k) is not None}
        sens = s.get("sensors", {})
        senses["distances"] = {k: sens.get(k) for k in ("US0", "US1", "Laser") if k in sens}
        if mind.vision_model():
            night = (s.get("cameras") or {}).get("NightCamSide", "left")
            eyes = {night: self.remote.frame0, ("right" if night == "left" else "left"): self.remote.frame1}
            for side, frame in eyes.items():
                jpeg = _jpeg(frame)
                if jpeg:
                    view = mind.see(jpeg, LOOK_QUESTION)
                    senses[f"{side}_eye_sees"] = view.get("objects", view)
        return senses

    def act(self, move, steps):
        r = self._get(f"/mind?act={move}&steps={steps}")
        if move == "stop" or not r.get("ok"):
            return r
        t0 = time.time()
        while time.time() - t0 < MOVE_TIMEOUT_S:
            time.sleep(0.3)
            s = self._get("/status?ctl=1")
            if not s.get("mindSteps"):
                return {"ok": True, "stopped_at_a_wall": bool(s.get("blocked"))}
        return {"ok": True, "note": "still moving"}

    def robot_say(self, text):
        try:
            wav = mind.windows_wav(text, *self.mind.voice)
            with open(wav, "rb") as f:
                r = requests.post(f"{self.remote.base_url}/speak", data=f.read(), timeout=10)
            os.remove(wav)
            return r.ok
        except Exception:
            return False   # mind.py says it on this PC instead

    # ── once a frame, from main.py ──
    def update(self, status):
        """Start the PC's mind when she's in MIND mode with the PC as her brain; stop it otherwise."""
        ours = (self.capable and self.remote.connected and status.get("mode") == "MIND"
                and status.get("mindBrain") == "pc")
        if ours and not self.mind.on and not (self.mind._thread and self.mind._thread.is_alive()):
            self.mind.start(goal=status.get("mindGoal") or "explore the room, say what you notice, and don't bump into anything")
        elif not ours and self.mind.on:
            self.mind.on = False
            self.mind.state = "off"

    def shown(self, status):
        """What the mind panel shows: the PC's mind, her own (status mindSelf), or None."""
        if self.mind.on:
            return self.mind, "this PC"
        own = status.get("mindSelf")
        if status.get("mode") == "MIND" and own:
            return SimpleNamespace(on=True, state=own.get("state", ""), thinking=own.get("thinking", ""),
                                   said=own.get("said", ""), error=own.get("error", "")), "on her Pi"
        return None, ""


def _jpeg(frame):
    if frame is None:
        return None
    import cv2
    ok, buf = cv2.imencode(".jpg", cv2.cvtColor(frame, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 80])
    return buf.tobytes() if ok else None
