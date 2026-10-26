# fake_kida01.py — a pretend KIDA-01 for the controller's EMULATE (fleet TODO section 13).
#
# Answers her Flask server's routes (scripts/server.py) the way she does, on 127.0.0.1:5004,
# with a pretend room to drive round, so every key, button and pad input of controller/main.py
# can be tried with no robot:
#
#   GET  /status              what server.py's /status gives (mode, speed, sensors, power, mind...)
#   POST /action              {"command": ...}: the same commands as web_bridge.action()
#   GET  /video_feed/0, /1    MJPEG: cam 0 the room from above, cam 1 what she sees ahead
#   GET  /last_photo          the photo she took last (C / Take Photo)
#   GET  /character_face      her avatar
#   GET  /mind                her inner life (mood, drives, a thought); ?act=&steps= her MIND moves
#   GET  /unlock /mode, POST /speak, GET/POST /options.json
#
# Run it alone (python fake_kida01.py) and point the controller at 127.0.0.1, or press EMULATE
# in the controller: it starts one of these inside itself.

import io
import json
import math
import os
import random
import sys
import time
from collections import deque

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))   # drive_mix

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame

import controller_kit as kit
from drive_mix import curve_speeds

ROOM_W, ROOM_H = 500.0, 360.0           # cm
BOXES = [(130, 70, 70, 50), (300, 200, 60, 90), (70, 250, 50, 50), (400, 60, 40, 40)]
TOP_CM_S = 50.0                          # full speed (255), both tracks forward
TURN_CM = 40.0                           # a skid-steer turns as if her tracks were this far apart
HEARTBEAT_S = 0.8                        # web_bridge: a drive not heard of for this long stops
WALL_CM = 25.0                           # no forward past this (her bumpers / wall guard)
AUTO_TURN_CM = 40.0
MIN_SPEED, MAX_SPEED, SPEED_STEP = 100, 255, 50   # config.py
PIN = "1234"                             # her MotorPassword while config.json's is empty
MODES = {1: "KEYBOARD", 2: "IR_REMOTE", 3: "AUTONOMOUS", 4: "IDLE", 5: "LINE_FOLLOWER",
         6: "WATCHDOG", 7: "LANE_DETECT", 8: "PERSON_FOLLOW", 9: "MIND"}
HOST_TTL_S = 5.0
MIND_STEP_S = 0.4
CAM_W, CAM_H = 320, 240
FOV = math.radians(62)


class FakeKida01(kit.FakeRobot):
    NAME = "KIDA01"
    PORTS = (5004,)

    def __init__(self, host="127.0.0.1"):
        self.x, self.y, self.heading = 50.0, 50.0, 0.0
        self.mode = "KEYBOARD"
        self.speed = MAX_SPEED
        self.scheme = "WASD"
        self.tracks = [0.0, 0.0]          # -1..1 each (before the speed setting)
        self.drive_until = 0.0
        self.motor_lock = False
        self.music_on = False
        self.inference_on = False
        self.recording = False
        self.leds = True
        self.cam_id = 0
        self.servo = 90
        self.last_photo = None
        self.last_photo_ts = None
        self.host_seen = -1e9
        self.mind_move = {"steps": 0, "dir": None, "until": 0.0, "blocked": False}
        self.exchange = None
        self.config = {"MotorPassword": "", "Mind": {"Where": "pc", "Goal": ""}, "Name": "KIDA-01 (pretend)"}
        self.started = time.time()
        self.drop = 0                      # session_test.py: lose this many commands, as a busy robot can
        self.heard = deque(maxlen=200)     # the commands she took, in order (session_test.py)
        super().__init__(host)

    # ── her world ──────────────────────────────────────────────────────────
    def distance(self, heading=None, max_cm=400):
        h = self.heading if heading is None else heading
        dx, dy = math.cos(h), math.sin(h)
        for d in range(0, max_cm, 2):
            px, py = self.x + dx * d, self.y + dy * d
            if not (0 < px < ROOM_W and 0 < py < ROOM_H) or any(
                    bx <= px <= bx + bw and by <= py <= by + bh for bx, by, bw, bh in BOXES):
                return float(d)
        return float(max_cm)

    def _wanted(self, now):
        if self.mode == "AUTONOMOUS":
            return (0.7, -0.7) if self.distance() < AUTO_TURN_CM else (1.0, 1.0)
        if self.mode == "LINE_FOLLOWER":
            return (0.6, 0.45)
        if self.mode == "PERSON_FOLLOW":
            return (0.4, 0.4) if self.distance() > 80 else (0.0, 0.0)
        if self.mode == "MIND":
            m = self.mind_move
            if m["steps"] > 0:
                return {"fwd": (1, 1), "bwd": (-1, -1), "left": (-1, 1), "right": (1, -1)}.get(m["dir"], (0, 0))
            return (0.0, 0.0)
        if self.mode != "KEYBOARD" or now > self.drive_until:
            return (0.0, 0.0)
        return tuple(self.tracks)

    def step(self, dt):
        now = time.monotonic()
        if self.mode == "MIND" and now - self.host_seen > HOST_TTL_S:
            self.mode = "KEYBOARD"
            self.log("MIND host gone quiet: back to KEYBOARD")
        m = self.mind_move
        if m["steps"] > 0 and now >= m["until"]:
            m["steps"] -= 1
            m["until"] = now + MIND_STEP_S
        l, r = (0.0, 0.0) if self.motor_lock else self._wanted(now)
        if l > 0 and r > 0 and self.distance() < WALL_CM:
            l, r = 0.0, 0.0
            if m["steps"] and m["dir"] == "fwd":
                m.update(steps=0, blocked=True)
        v = (l + r) / 2 * TOP_CM_S * self.speed / MAX_SPEED
        self.heading -= (l - r) * TOP_CM_S * self.speed / MAX_SPEED / TURN_CM * dt
        nx, ny = self.x + math.cos(self.heading) * v * dt, self.y + math.sin(self.heading) * v * dt
        if 10 < nx < ROOM_W - 10 and 10 < ny < ROOM_H - 10 and not any(
                bx - 10 <= nx <= bx + bw + 10 and by - 10 <= ny <= by + bh + 10 for bx, by, bw, bh in BOXES):
            self.x, self.y = nx, ny
        self.moving = bool(l or r)

    # ── web_bridge.action() ────────────────────────────────────────────────
    def action(self, command, data):
        now = time.monotonic()
        drive_cmds = {"move_forward", "move_backward", "move_left", "move_right", "move_curve", "joy_drive",
                      "left_forward", "left_backward", "right_forward", "right_backward", "left_stop",
                      "right_stop", "move_stop", "hard_stop", "servo_aim"}
        if self.drop > 0 and command not in drive_cmds:
            self.drop -= 1
            self.log(f"(lost {command}, on purpose)")
            return True   # she answered, but it never reached her loop
        self.heard.append(command)

        def drive(l, r):
            if self.mode == "KEYBOARD":
                self.tracks = [float(l), float(r)]
                self.drive_until = now + HEARTBEAT_S

        def unit(v):
            try:
                return max(-1.0, min(1.0, float(v)))
            except (TypeError, ValueError):
                return 0.0

        if command.startswith("mode_"):
            try:
                n = int(command[5:])
            except ValueError:
                return False
            if n == 9:
                if now - self.host_seen > HOST_TTL_S:
                    self.log("MIND: no mind can drive her now")
                    return False
            if n not in MODES:
                return False
            self.mode = MODES[n]
            self.tracks, self.mind_move["steps"] = [0.0, 0.0], 0
        elif command == "move_forward":   drive(1, 1)
        elif command == "move_backward":  drive(-1, -1)
        elif command == "move_left":      drive(-1, 1)
        elif command == "move_right":     drive(1, -1)
        elif command == "move_curve":
            l, r = curve_speeds(1 if unit(data.get("throttle")) >= 0 else -1,
                                1 if unit(data.get("turn")) >= 0 else -1, 100)
            drive(l / 100, r / 100)
        elif command == "joy_drive":
            l, r = unit(data.get("left")), unit(data.get("right"))
            if self.mode == "KEYBOARD":
                self.tracks = [l, r]
                self.drive_until = now + HEARTBEAT_S if (l or r) else 0.0
        elif command in ("left_forward", "left_backward", "right_forward", "right_backward"):
            if self.mode == "KEYBOARD":
                side, way = command.split("_")
                self.tracks[0 if side == "left" else 1] = 1.0 if way == "forward" else -1.0
                self.drive_until = now + HEARTBEAT_S
        elif command == "left_stop":      self.tracks[0] = 0.0
        elif command == "right_stop":     self.tracks[1] = 0.0
        elif command in ("move_stop", "hard_stop"):
            self.tracks, self.drive_until = [0.0, 0.0], 0.0
            if command == "hard_stop":
                self.music_on = False
        elif command == "scheme_wasd":    self.scheme = "WASD"
        elif command == "scheme_qaws":    self.scheme = "QAWS"
        elif command == "speed_cycle":
            self.speed = self.speed + SPEED_STEP if self.speed + SPEED_STEP <= MAX_SPEED else MIN_SPEED
        elif command == "speed_up":       self.speed = min(self.speed + SPEED_STEP, MAX_SPEED)
        elif command == "speed_down":     self.speed = max(self.speed - SPEED_STEP, MIN_SPEED)
        elif command == "music_play":     self.music_on = True
        elif command == "music_skip":     self.log("next track")
        elif command == "music_stop":     self.music_on = False
        elif command == "photo":
            self.last_photo, self.last_photo_ts = self._frame(1), round(time.time(), 3)
        elif command == "video_start":    self.recording = True
        elif command == "video_stop":     self.recording = False
        elif command == "video_toggle":   self.recording = not self.recording
        elif command == "save_inference": self.log("inference photo saved")
        elif command == "camera_switch":  self.cam_id = 1 - self.cam_id
        elif command == "servo_aim":
            if self.mode not in ("KEYBOARD", "IDLE"):
                return False
            try:
                self.servo = max(0, min(180, int(float(data.get("angle")))))
            except (TypeError, ValueError):
                return False
        elif command == "inference_toggle": self.inference_on = not self.inference_on
        elif command == "leds_toggle":    self.leds = not self.leds
        elif command == "leds_effects_toggle": pass
        elif command == "motor_lock_on":  self.motor_lock = True
        elif command == "motor_lock_off":
            if (data.get("password") or "") != PIN:
                return False
            self.motor_lock = False
        elif command == "chat":
            text = str(data.get("text") or "").strip()
            if not text:
                return False
            self.exchange = {"you": text[:500], "kida": random.choice(
                ["I'm only pretending to be me, but I heard you.", "Mm. Tell me more.",
                 "I'd answer properly if I were really here."])}
        elif command in ("go_home", "set_home", "nav_stop", "lidar_sweep", "calibrate_wheels", "trim_up",
                         "trim_down", "voice_mode_wakeword", "voice_mode_always_on", "chirp",
                         "route_record_start", "route_record_stop", "route_play", "route_patrol",
                         "route_delete", "face_enroll", "face_forget"):
            self.log(f"{command}: pretend")
        else:
            return False
        if command not in drive_cmds:
            self.log(f"{command}  ->  mode {self.mode}, speed {self.speed}, scheme {self.scheme}")
        return True

    # ── routes ─────────────────────────────────────────────────────────────
    def status(self):
        now = time.monotonic()
        host = now - self.host_seen < HOST_TTL_S
        us0, us1 = self.distance(), self.distance(self.heading + math.radians(self.servo - 90))
        t = time.time() - self.started
        return {
            "name": self.NAME, "ip": "127.0.0.1", "mode": self.mode, "voice_mode": "WAKEWORD",
            "cpu_temp": f"{52 + 2 * math.sin(t / 20):.1f}°C", "cpu": round(22 + 8 * random.random(), 1),
            "ram": 41.0, "motor_speed": self.speed, "music_on": self.music_on,
            "inference_on": self.inference_on, "motor_lock": self.motor_lock, "tipped": False,
            "drive_scheme": self.scheme, "active_cam_id": self.cam_id, "last_photo_ts": self.last_photo_ts,
            "bus_v": 7.6, "cur_ma": 900.0 if self.moving else 420.0, "pwr_w": 6.8 if self.moving else 3.2,
            "bat_pct": 78, "rumble": {"low": 0.4 if us0 < WALL_CM else 0.0, "high": 0.0, "reason": ""},
            "pose": {"x": round(self.x), "y": round(self.y), "heading": round(math.degrees(self.heading))},
            "person": None, "recording": self.recording, "emulated": True,
            "mindHost": int(host), "mindSteps": self.mind_move["steps"], "blocked": self.mind_move["blocked"],
            "mindBrain": "pc" if host else None, "mindWhere": "pc", "mindAvailable": host, "mindGoal": "",
            "cameras": {"NightCamSide": "front"},
            "sensors": {"Photo": 612, "UV": 0.3, "Metal": 0, "Ball Sw": 0, "Motion": 0,
                        "LF L": 0, "LF M": 1 if self.mode == "LINE_FOLLOWER" else 0, "LF R": 0,
                        "Laser": round(us1 * 10), "US0": round(us0, 1), "US1": round(us1, 1),
                        "AX": 0.01, "AY": -0.02, "AZ": 0.98, "GX": 0.0, "GY": 0.0,
                        "GZ": round(math.degrees((self.tracks[0] - self.tracks[1]) * 0.5), 1),
                        "Status": "pretend"},
        }

    moving = False

    def route(self, port, path, q):
        if path == "/status":
            if q.get("ctl") == "1":
                self.host_seen = time.monotonic()
            return 200, self.status()
        if path == "/action" and "_body" in q:
            data = q.get("_json", {})
            cmd = str(data.get("command", ""))
            return 200, {"ok": self.action(cmd, data), "command": cmd}
        if path in ("/video_feed/0", "/video_feed/1"):
            return 200, self._mjpeg(int(path[-1])), "multipart/x-mixed-replace; boundary=frame"
        if path == "/last_photo":
            return (200, self.last_photo, "image/jpeg") if self.last_photo else (404, "no photo yet")
        if path == "/character_face":
            try:
                with open(os.path.join(_ROOT, "images", "avatar_round.png"), "rb") as f:
                    return 200, f.read(), "image/png"
            except OSError:
                return 404, "no face"
        if path == "/mind":
            if "act" in q:
                return self._mind_act(q.get("act", ""), q.get("steps", "1"))
            t = time.time() - self.started
            return 200, {"mood": {"label": "curious (pretend)"},
                         "drives": {"social": 0.4 + 0.2 * math.sin(t / 30), "curiosity": 0.7,
                                    "security": 0.2, "sleepiness": 0.1},
                         "thought": "I'm a pretend KIDA on this PC. The boxes in this room never move.",
                         "sleeping": False, "person": None, "last_exchange": self.exchange}
        if path == "/unlock":
            if q.get("pw") != PIN:
                return 403, {"ok": False, "error": "wrong PIN"}
            if q.get("ctl") == "1":
                self.host_seen = time.monotonic()
                self.log("a mind host signed in")
            else:
                self.motor_lock = False
            return 200, {"ok": True, "motor_lock": self.motor_lock}
        if path == "/mode":
            names = {"keyboard": 1, "kb": 1, "ir": 2, "auto": 3, "idle": 4, "line": 5, "watchdog": 6,
                     "lane": 7, "follow": 8, "mind": 9}
            m = (q.get("m") or "").lower()
            if m not in names:
                return 400, {"ok": False, "error": "m is mind, keyboard, ir, auto, idle, line, watchdog, lane or follow"}
            ok = self.action(f"mode_{names[m]}", {})
            return (200 if ok else 409), {"ok": ok}
        if path == "/speak":
            self.log(f"speaks a WAV of {len(q.get('_body', b''))} bytes")
            return 200, {"ok": True}
        if path == "/options.json":
            if "_json" in q:
                if (q["_json"].get("password") or "") != PIN:
                    return 403, {"ok": False, "error": "wrong PIN"}
                self.config = q["_json"].get("config", self.config)
                return 200, {"ok": True}
            return 200, {"config": self.config, "choices": {}}
        if path == "/ping":
            return 200, {"ok": True, "name": self.NAME}
        if path == "/haptics":
            return 200, self.status()["rumble"]
        return 404, {"error": f"KIDA01 (pretend) has no {path}"}

    def _mind_act(self, move, steps):
        if time.monotonic() - self.host_seen > HOST_TTL_S:
            return 403, {"ok": False, "error": "only her mind host"}
        if self.mode != "MIND":
            return 409, {"ok": False, "error": "not in MIND mode with the PC driving"}
        if move == "stop":
            self.mind_move["steps"] = 0
            return 200, {"ok": True}
        if move == "fwd" and self.distance() < WALL_CM:
            self.mind_move["blocked"] = True
            return 200, {"ok": False, "blocked": True, "front_cm": round(self.distance(), 1)}
        if move not in ("fwd", "bwd", "left", "right"):
            return 400, {"ok": False, "error": f"no move {move}"}
        if self.mind_move["steps"]:
            return 409, {"ok": False, "error": "still moving"}
        try:
            n = max(1, min(4, int(steps or 1)))
        except ValueError:
            n = 1
        self.mind_move.update(steps=n, dir=move, until=time.monotonic() + MIND_STEP_S, blocked=False)
        self.log(f"MIND: {move} x{n}")
        return 200, {"ok": True}

    # ── her cameras ────────────────────────────────────────────────────────
    def _frame(self, cam):
        s = pygame.Surface((CAM_W, CAM_H))
        if cam == 0:      # from above: the room, her, her sonar
            s.fill((18, 20, 30))
            k = min(CAM_W / ROOM_W, CAM_H / ROOM_H)
            ox, oy = (CAM_W - ROOM_W * k) / 2, (CAM_H - ROOM_H * k) / 2

            def p(x, y):
                return int(ox + x * k), int(oy + (ROOM_H - y) * k)

            pygame.draw.rect(s, (60, 70, 100), (*p(0, ROOM_H), int(ROOM_W * k), int(ROOM_H * k)), 2)
            for bx, by, bw, bh in BOXES:
                pygame.draw.rect(s, (120, 90, 70), (*p(bx, by + bh), int(bw * k), int(bh * k)))
            d = self.distance()
            hx, hy = math.cos(self.heading), math.sin(self.heading)
            pygame.draw.line(s, (255, 190, 80), p(self.x, self.y), p(self.x + hx * d, self.y + hy * d), 1)
            pts = [(self.x + hx * 14, self.y + hy * 14), (self.x - hx * 9 - hy * 9, self.y - hy * 9 + hx * 9),
                   (self.x - hx * 9 + hy * 9, self.y - hy * 9 - hx * 9)]
            pygame.draw.polygon(s, (255, 140, 220), [p(*q) for q in pts])
        else:             # ahead of her: a wall for every column, nearer is taller
            s.fill((40, 36, 52), (0, 0, CAM_W, CAM_H // 2))
            s.fill((70, 62, 58), (0, CAM_H // 2, CAM_W, CAM_H // 2))
            for c in range(0, CAM_W, 4):
                a = self.heading + FOV / 2 - FOV * c / CAM_W
                d = max(1.0, self.distance(a, 500) * math.cos(a - self.heading))
                h = min(CAM_H, int(CAM_H * 30 / d))
                shade = max(40, min(220, int(240 - d * 0.5)))
                s.fill((shade, int(shade * 0.85), int(shade * 0.75)), (c, (CAM_H - h) // 2, 4, h))
        buf = io.BytesIO()
        pygame.image.save(s, buf, "frame.jpg")
        return buf.getvalue()

    def _mjpeg(self, cam):
        while not self._stop.is_set():
            jpg = self._frame(cam)
            yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n"
            time.sleep(0.12)


if __name__ == "__main__":
    robot = FakeKida01()
    print("Pretend KIDA-01 on http://127.0.0.1:5004  (Ctrl+C stops it)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        robot.stop()
