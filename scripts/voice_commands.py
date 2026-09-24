# voice_commands.py — map spoken phrases to robot control actions
#
# Called from kida_chat_wakeword._task_worker before falling through to LLM.
# If a phrase matches a command, the action is executed and the LLM is skipped.

import re

# ── Pattern → action key ────────────────────────────────────────────────────
# Narration and video-recording "stop ..." phrases must come before the
# generic "stop" pattern below — otherwise "stop narrating"/"stop recording"
# would match \bstop\b first and trigger a full motor stop instead.
_COMMANDS = [
    # Faces, home and routes come first: "start recording a route" and "stop
    # the patrol" must not be taken for video recording / a motor stop.
    (r"\b(remember|learn) (this face|them|him|her) as (?P<name>[a-z]+)", "face_enroll_named"),
    (r"\b(remember|learn) my face\b|\bremember me\b|\blearn my face\b",            "face_enroll"),
    (r"\bforget my face\b",                                                       "face_forget"),
    (r"\b(go|come|drive|head) (back )?home\b|\bgo back to (the )?start\b|\breturn home\b", "go_home"),
    (r"\b(this is home|set home|make this home|remember this spot)\b",                 "set_home"),
    (r"\b(start|begin) recording (a |the )?route|\brecord (a |the )?route",           "route_record"),
    (r"\b(stop|finish|save|end) (recording )?(the |this )?route\b",                   "route_save"),
    (r"\bstop (the )?patrol(ling)?\b|\bstop (the )?route\b",                           "route_stop"),
    (r"\bpatrol",                                                                   "route_patrol"),
    (r"\b(replay|run|drive|follow|do) (the )?(?P<name>[a-z ]+?) route\b",           "route_play"),
    (r"\b(stop narrating|stop describing|quiet down|stay quiet)\b",       "narrate_off"),
    (r"\b(start narrating|describe your surroundings|describe what you see|keep me posted)\b", "narrate_on"),
    (r"\b(what do you see|where are you|look around)\b",                 "narrate_once"),
    (r"\b(stop recording|stop the video|end recording|stop filming)\b",   "video_stop"),
    (r"\b(take a picture|take a photo|snap a photo|snap a picture)\b",    "photo"),
    (r"\b(record a? ?video|start recording|film this|start filming)\b",  "video_start"),
    (r"\b(switch camera|change camera|other camera|next camera|swap camera)\b", "camera_switch"),
    (r"\b(stop|halt|emergency stop|full stop|freeze)\b",        "stop"),
    (r"\b(play music|play song|play track|start music)\b",      "music_play"),
    (r"\b(next track|skip track|skip song|next song|skip)\b",   "music_skip"),
    (r"\b(stop music|mute music|no music|quiet|silence)\b",     "music_stop"),
    (r"\b(keyboard mode|manual mode|take control|drive)\b",     "mode_keyboard"),
    (r"\b(autonomous mode|auto mode|self.?driv)\b",             "mode_autonomous"),
    (r"\b(line follow|line follower|follow the line|follow line)\b", "mode_line_follow"),
    (r"\b(idle|sleep mode|standby|do nothing)\b",               "mode_idle"),
    (r"\b(watchdog|watch mode|guard mode|sentry|alarm mode)\b", "mode_watchdog"),
    (r"\b(lane detect|lane detection|follow lane|detect lane)\b","mode_lane"),
]

_REPLIES = {
    "stop":             "All motors stopped.",
    "narrate_off":      "Going quiet. Wake me if you need me.",
    "narrate_on":       "You got it — I'll keep you posted.",
    "photo":            "Got it, say cheese!",
    "video_start":      "Recording now.",
    "video_stop":       "Stopped recording.",
    "music_play":       "Playing music.",
    "music_skip":       "Next track.",
    "music_stop":       "Music off.",
    "mode_keyboard":    "Switching to keyboard mode.",
    "mode_autonomous":  "Going autonomous. Try to keep up.",
    "mode_line_follow": "Activating line follower.",
    "mode_idle":        "Entering idle mode.",
    "mode_watchdog":    "Watchdog mode active. I'm watching.",
    "mode_lane":        "Lane detection active.",
}


def _norm(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text.lower()).strip()


_last_text = ""   # the phrase dispatch() matched, for commands that carry a name


def dispatch(text: str) -> str | None:
    """Return an action key if text matches a control command, else None."""
    global _last_text
    n = _norm(text)
    for pattern, key in _COMMANDS:
        if re.search(pattern, n):
            _last_text = n
            return key
    return None


def _route_name(text: str, default: str = "my route") -> str:
    m = (re.search(r"(?:called|named) ([a-z0-9 ]+?)(?: route)?$", text)
         or re.search(r"patrol (?:the )?([a-z0-9 ]+?)(?: route)?$", text)
         or re.search(r"(?:replay|run|drive|follow|do) (?:the )?([a-z0-9 ]+?) route", text))
    name = m.group(1).strip() if m else ""
    return name if name and name not in ("a", "the", "route", "again") else default


def _known_name() -> str | None:
    """The user's name, if she's been told it ("my name is Sam")."""
    try:
        from kida_mind import facts
        for _, kind, fact in reversed(facts.read_memories()):
            if kind == "name":
                m = re.search(r"name is (\w+)", fact)
                if m:
                    return m.group(1)
    except Exception:
        pass
    return None


def _execute_extra(action: str, say) -> bool:
    """Faces, home and routes. Returns True if it was one of these."""
    text = _last_text
    if action in ("face_enroll", "face_enroll_named"):
        import face_id
        if not face_id.available():
            say("I can't learn faces yet. My face model isn't installed.")
            return True
        m = re.search(r"as ([a-z]+)", text)
        name = m.group(1).title() if (action == "face_enroll_named" and m) else _known_name()
        if not name:
            say("Tell me your name first. Say, my name is, and then your name.")
            return True
        say(f"Okay {name}, look at me for a few seconds.")
        say(f"Got it. I'll remember you, {name}." if face_id.enroll(name)
            else "I couldn't get a good look. Try again, facing me, a bit closer.")
        return True
    if action == "face_forget":
        import face_id, state
        name = state.person_name or _known_name()
        say("Done. I've forgotten your face." if name and face_id.forget(name)
            else "I didn't have your face saved.")
        return True
    if action == "go_home":
        import navigator, mode_manager
        if not mode_manager.is_keyboard():
            say("Put me in keyboard mode first, then I'll head home.")
        elif navigator.go_home():
            say("Heading home.")
        else:
            say("I'm already home." if not navigator.active() else "I'm busy driving somewhere already.")
        return True
    if action == "set_home":
        import odometry
        odometry.set_home()
        say("Okay. This spot is home now.")
        return True
    if action == "route_record":
        import routes
        name = _route_name(text)
        say(f"Recording the {name} route. Drive me along it, then say save the route."
            if routes.record_start(name) else "I'm already recording, or driving a route.")
        return True
    if action == "route_save":
        import routes
        r = routes.record_stop()
        say(f"Saved the {r['name']} route, with {len(r['waypoints'])} stops." if r
            else "There was no route to save, or it was too short.")
        return True
    if action == "route_stop":
        import routes
        routes.stop()
        say("Stopping.")
        return True
    if action in ("route_patrol", "route_play"):
        import routes, mode_manager
        saved = [r["name"] for r in routes.list_routes()]
        name = _route_name(text, default=saved[0] if len(saved) == 1 else "my route")
        if not mode_manager.is_keyboard():
            say("Put me in keyboard mode first.")
        elif not routes.load(name):
            say(f"I don't know a route called {name}." + (f" I know {', '.join(saved)}." if saved else ""))
        elif routes.play(name, patrol=action == "route_patrol"):
            say(f"Patrolling the {name} route. Say stop patrolling to end it." if action == "route_patrol"
                else f"Driving the {name} route.")
        else:
            say("I can't start that right now.")
        return True
    return False


def execute(action: str, speak_fn=None) -> bool:
    """
    Run a robot control action.
    speak_fn: optional callable(text) to give audio feedback.
    Returns True if the action was handled.
    """
    try:
        from mode_control import switch_mode
        import web_bridge
    except ImportError as e:
        print(f"⚠️ voice_commands import error: {e}")
        return False

    if _execute_extra(action, speak_fn or (lambda t: print(f"🔊 {t}"))):
        print(f"🎤 Voice command executed: {action}")
        return True

    if   action == "stop":             switch_mode(4)
    elif action == "music_play":       web_bridge.action("music_play")
    elif action == "music_skip":       web_bridge.action("music_skip")
    elif action == "music_stop":       web_bridge.action("music_stop")
    elif action == "mode_keyboard":    switch_mode(1)
    elif action == "mode_autonomous":  switch_mode(3)
    elif action == "mode_line_follow": switch_mode(5)
    elif action == "mode_idle":        switch_mode(4)
    elif action == "mode_watchdog":    switch_mode(6)
    elif action == "mode_lane":        switch_mode(7)
    elif action == "narrate_on":
        import ambient_narration
        ambient_narration.set_enabled(True)
    elif action == "narrate_off":
        import ambient_narration
        ambient_narration.set_enabled(False)
    elif action == "narrate_once":
        import ambient_narration
        ambient_narration.describe_now(block=True)
        print("🎤 Voice command executed: narrate_once")
        return True
    elif action == "photo":
        import camera_actions
        camera_actions.take_photo()
    elif action == "video_start":
        import camera_actions
        camera_actions.start_video()
    elif action == "video_stop":
        import camera_actions
        camera_actions.stop_video()
    elif action == "camera_switch":
        import camera_actions
        cam_id   = camera_actions.cycle_camera()
        cam_name = "the main camera" if cam_id == 0 else "the A I camera"
        if speak_fn:
            speak_fn(f"Switching to {cam_name}.")
        print(f"🎤 Voice command executed: {action}")
        return True
    else:
        return False

    if speak_fn:
        speak_fn(_REPLIES.get(action, "Done."))

    # Sound effects play AFTER she's done talking — speak_fn (kida_chat's
    # piper speak()) blocks until playback finishes, so by this point the
    # reply has already been heard.
    if action == "photo":
        import sfx
        sfx.play("camera_shutter.mp3")
    elif action == "video_start":
        import sfx
        sfx.play("video_reel.mp3")

    print(f"🎤 Voice command executed: {action}")
    return True
