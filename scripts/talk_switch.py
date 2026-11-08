"""talk_switch.py - a robot's two talk switches (RIFT's Fleet/talk_mute.py).

    sound    talk_muted  her Brainfuck isn't beeped: she still takes part in the conversations,
                         silently (RIFT's log still shows what she said)
    chat     chat_off    she's out of the conversation engine: RIFT leaves her out of the chatter,
                         and she doesn't start or answer conversations herself (peer talks too)

The master copy is RIFT/Fleet/talk_switch.py; the Python robots (DREAM, TINA, NINA, AURA,
KIDA-00, KIDA-01, ARM) carry it byte for byte. It keeps both in a small JSON file next to the
robot's program, so a restart keeps them, and gives her Flask app the fleet's route:

    GET /talkmute                     {"talk_muted": bool, "chat_off": bool}
    GET /talkmute?on=1|0|toggle       the sound switch      (no PIN: it only makes her quieter)
    GET /talkmute?chat_off=1|0|toggle the chat switch

In her /chirp:

    if TALK.chat_off: return TALK.refuse()   # 409 {"reason": "chat_off"}: RIFT leaves her out
    if TALK.muted: return TALK.silent()      # 200 {"ok": true, "silent": true}: said, not beeped

    TALK = talk_switch.TalkSwitch(os.path.join(HERE, "talk_mute.json"))
    TALK.register(app)
    PeerTalk(..., muted=lambda: TALK.muted, chat_off=lambda: TALK.chat_off)
    status["talk_muted"], status["chat_off"] = TALK.muted, TALK.chat_off
"""
import json
import os
import threading


def _flag(value, now):
    """?on= / ?chat_off= : 1, 0, true, false or toggle -> the new value (None: not a value)."""
    v = str(value).lower()
    if v == "toggle":
        return not now
    if v in ("1", "true"):
        return True
    if v in ("0", "false"):
        return False
    return None


class TalkSwitch:
    def __init__(self, path, on_change=None):
        self.path = path
        self.on_change = on_change      # called with (muted, chat_off) after a change (e.g. to tell an Arduino)
        self._lock = threading.Lock()
        self._muted = False
        self._chat_off = False
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            self._muted = bool(d.get("talk_muted"))
            self._chat_off = bool(d.get("chat_off"))
        except (OSError, ValueError, AttributeError):
            pass

    @property
    def muted(self):
        return self._muted

    @property
    def chat_off(self):
        return self._chat_off

    def state(self):
        return {"talk_muted": self._muted, "chat_off": self._chat_off}

    def set(self, muted=None, chat_off=None):
        with self._lock:
            before = (self._muted, self._chat_off)
            if muted is not None:
                self._muted = bool(muted)
            if chat_off is not None:
                self._chat_off = bool(chat_off)
            try:
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.state(), f)
                os.replace(tmp, self.path)
            except OSError as e:
                print(f"[talk] couldn't save {self.path}: {e}")
            after = (self._muted, self._chat_off)
        if after != before and self.on_change:
            try:
                self.on_change(*after)
            except Exception as e:
                print(f"[talk] {e}")
        return self.state()

    def refuse(self):
        """/chirp with the chat switch off: RIFT leaves her out."""
        from flask import jsonify
        return jsonify({"ok": False, "reason": "chat_off"}), 409

    def silent(self):
        """/chirp with the sound switch off: she said it, without a beep."""
        from flask import jsonify
        return jsonify({"ok": True, "silent": True})

    def register(self, app):
        from flask import jsonify, request

        @app.route("/talkmute")
        def talkmute():
            muted = _flag(request.args.get("on"), self._muted) if "on" in request.args else None
            chat = _flag(request.args.get("chat_off"), self._chat_off) if "chat_off" in request.args else None
            if muted is not None or chat is not None:
                self.set(muted, chat)
            return jsonify(self.state())
