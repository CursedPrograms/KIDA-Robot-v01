#!/usr/bin/env python3
"""
fleet_music.py — KIDA-01 plays along when the fleet plays music together (RIFT conducts).

The same contract as KIDA-00's fleet_music.py and TINA/tina/music.py: RIFT sends
POST /music {"action": "play", "track": 7, "at": <RIFT's time>}. She loads the song
straight away, then starts it at that moment on RIFT's clock, so she's in time with
NORA, TINA and the others however long the message took. Her offset to RIFT's clock
comes from RIFT's GET /clock on :5000 (whoever sent the command: only RIFT conducts),
refreshed every CLOCK_S; MUSIC_LATENCY takes off her own start-up lag. "pause",
"resume" and "stop" are timed the same way; a newer command cancels one still waiting.

Tracks are numbered by the number in the file name (track07.mp3 is 7), as on NORA's
SD card. She plays through ui.py's MusicPlayer (web_bridge.register_music). server.py
serves /music and registers "music:5004" so RIFT includes her.
"""

import logging
import threading
import time

import requests

import web_bridge

logger = logging.getLogger("kida.music")

CLOCK_S       = 60     # re-read RIFT's clock this often
MUSIC_LATENCY = 0.0    # s her speaker lags; taken off so she starts in time with the others

_offset = {"s": 0.0, "at": 0.0, "url": ""}   # RIFT's clock minus hers
_seq    = {"n": 0}                           # a newer command cancels a waiting one
now: dict = {}                               # {"track", "state", "late_ms"} for GET /music


def sync(rift_url: str) -> float:
    """Her offset to RIFT's clock: half the round trip either side of RIFT's answer."""
    if not rift_url or (rift_url == _offset["url"] and time.time() - _offset["at"] < CLOCK_S):
        return _offset["s"]
    t0 = time.time()
    rift = requests.get(f"{rift_url}/clock", timeout=2).json()["t"]
    t1 = time.time()
    _offset.update(s=rift - (t0 + t1) / 2, at=t1, url=rift_url)
    return _offset["s"]


def command(body: dict, rift_url: str) -> tuple:
    """RIFT's command. Returns (json, http status) at once; the start waits on its own thread."""
    player = web_bridge._music_ctrl
    if player is None:
        return {"ok": False, "error": "her music player isn't running (ui.py)"}, 503
    action = str(body.get("action", "")).lower()
    if action not in ("play", "pause", "resume", "stop"):
        return {"ok": False, "error": "action is play, pause, resume or stop"}, 400
    track = None
    if action == "play":
        try:
            track = int(body.get("track"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "play needs a track number"}, 400
        if not player.load_number(track):
            return {"ok": False, "error": f"no track {track} in her music folder"}, 404
    try:
        offset = sync(rift_url)
    except (requests.RequestException, ValueError, KeyError):
        offset = _offset["s"]                     # RIFT's clock unreachable: the last offset
    at = body.get("at")
    start = (float(at) - offset - MUSIC_LATENCY) if at else time.time()
    _seq["n"] += 1
    threading.Thread(target=_at, args=(_seq["n"], start, action, track), daemon=True,
                     name="fleet-music").start()
    return {"ok": True, "starts_in_s": round(start - time.time(), 3), "offset_s": round(offset, 4)}, 200


def _at(seq: int, start: float, action: str, track) -> None:
    while time.time() < start - 0.02:
        time.sleep(min(0.05, start - time.time()))
    while time.time() < start:                    # the last few ms, busy-waited
        pass
    if seq != _seq["n"]:
        return
    player = web_bridge._music_ctrl
    if action == "play":
        player.start_loaded()
        now.update(track=track, state="playing", late_ms=round((time.time() - start) * 1000, 1))
    elif action == "pause":
        player.pause()
        now["state"] = "paused"
    elif action == "resume":
        player.resume()
        now["state"] = "playing"
    elif action == "stop":
        player.stop()
        now["state"] = "stopped"
    logger.info("Music with the fleet: %s %s", action, track if track is not None else "")


def status() -> dict:
    return {"now": now or None, "offset_s": round(_offset["s"], 4)}
