# session_test.py — drives the controller like a person, on her pretend self (fake_kida01.py),
# and checks every response (fleet TODO section 13's session test). No window, no robot:
#
#     venv/Scripts/python session_test.py        (Windows)    venv/bin/python session_test.py
#
# Keys held and tapped, her buttons clicked (modes, STOP, EMULATE), a command she loses on
# purpose (the controller sends it again), driving taking over from AUTONOMOUS, the motor lock
# and its PIN prompt, typing to her. A screenshot goes to session_test.png (not in git).

import os
import sys
import time

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")     # her controller prints emoji
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import pygame

W, H = 1600, 900
queue, results = [], []
seen = {"buttons": []}       # her buttons, as main.py hands them to event_handler


def key(k, down=True, ch=""):
    queue.append(pygame.event.Event(pygame.KEYDOWN if down else pygame.KEYUP, key=k, mod=0, unicode=ch, scancode=0))


def tap(k, ch=""):
    key(k, True, ch)
    key(k, False, ch)


def typed(text):
    for ch in text:
        tap(ord(ch.lower()) if ch.isalnum() else pygame.K_SPACE if ch == " " else ord(ch), ch)


def click(label):
    for b in seen["buttons"]:
        if b.label == label or b.label.startswith(label):
            pos = b.rect.center
            pygame.mouse.get_pos = lambda p=pos: p
            queue.append(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos))
            queue.append(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=pos))
            return
    results.append((False, f"no button {label!r}"))


def script(robot):
    def wait_for(what, cond, frames=90):          # 90 frames = 3 s at 30 fps
        for _ in range(frames):
            yield
            if cond():
                results.append((True, what))
                return
        results.append((False, what + f"   (she: mode {robot.mode}, tracks {robot.tracks}, speed {robot.speed}, "
                                       f"scheme {robot.scheme}, music {robot.music_on}, lock {robot.motor_lock})"))

    def frames(n):
        for _ in range(n):
            yield

    yield from frames(15)
    yield from wait_for("starts on her pretend self (no robot given)", lambda: robot.heard is not None and seen["buttons"])

    tap(pygame.K_x)
    yield from wait_for("X: next speed (255 -> 100)", lambda: robot.speed == 100)
    tap(pygame.K_PERIOD, ".")
    yield from wait_for(".: QAWS scheme", lambda: robot.scheme == "QAWS")
    tap(pygame.K_COMMA, ",")
    yield from wait_for(",: WASD scheme", lambda: robot.scheme == "WASD")

    x0 = robot.x
    key(pygame.K_w)
    yield from wait_for("W held: forward", lambda: robot.tracks == [1.0, 1.0] and robot.moving)
    yield from frames(30)
    results.append((robot.moving, "still going after 1 s held (the heartbeat)"))
    key(pygame.K_w, False)
    yield from wait_for("W let go: stops", lambda: not robot.moving)
    results.append((robot.x != x0, f"she moved ({x0:.0f} -> {robot.x:.0f} cm)"))

    key(pygame.K_w); key(pygame.K_a)
    yield from wait_for("W+A: curves left", lambda: robot.moving and robot.tracks[0] < robot.tracks[1])
    key(pygame.K_w, False); key(pygame.K_a, False)
    yield from wait_for("let go: stops", lambda: not robot.moving)

    tap(pygame.K_3)
    yield from wait_for("3: AUTONOMOUS", lambda: robot.mode == "AUTONOMOUS")
    yield from frames(20)
    key(pygame.K_s)
    yield from wait_for("S held in AUTONOMOUS: driving takes over (KEYBOARD, backward)",
                        lambda: robot.mode == "KEYBOARD" and robot.tracks == [-1.0, -1.0] and robot.moving)
    key(pygame.K_s, False)
    yield from wait_for("let go: stops", lambda: not robot.moving)

    tap(pygame.K_5)
    yield from wait_for("5: LINE FOLLOWER", lambda: robot.mode == "LINE_FOLLOWER")
    yield from frames(10)
    tap(pygame.K_BACKSPACE)
    yield from wait_for("Backspace: STOP in LINE FOLLOWER (KEYBOARD, stopped)",
                        lambda: robot.mode == "KEYBOARD" and not robot.moving)

    click("Autonomous")
    yield from wait_for("Autonomous button", lambda: robot.mode == "AUTONOMOUS")
    yield from frames(10)
    click("STOP")
    yield from wait_for("STOP button in AUTONOMOUS: KEYBOARD, stopped", lambda: robot.mode == "KEYBOARD" and not robot.moving)

    robot.drop = 1
    tap(pygame.K_3)
    yield from wait_for("3, and she loses it: sent again until she's AUTONOMOUS", lambda: robot.mode == "AUTONOMOUS")
    robot.drop = 1
    click("Keyboard Mode")
    yield from wait_for("Keyboard Mode button, lost once: sent again", lambda: robot.mode == "KEYBOARD")
    robot.drop = 1
    tap(pygame.K_PERIOD, ".")
    yield from wait_for("QAWS, lost once: sent again", lambda: robot.scheme == "QAWS")
    tap(pygame.K_COMMA, ",")
    yield from wait_for("WASD again", lambda: robot.scheme == "WASD")

    tap(pygame.K_m)
    yield from wait_for("M: music on", lambda: robot.music_on)
    tap(pygame.K_SPACE)
    yield from wait_for("Space: hard stop (music off too)", lambda: not robot.music_on)
    click("Play Music")
    yield from wait_for("Play Music button", lambda: robot.music_on)
    click("Stop Music")
    yield from wait_for("Stop Music button", lambda: not robot.music_on)

    tap(pygame.K_c)
    yield from wait_for("C: photo (her last photo panel gets it)", lambda: robot.last_photo_ts is not None)
    tap(pygame.K_i)
    yield from wait_for("I: inference on", lambda: robot.inference_on)
    tap(pygame.K_i)
    yield from wait_for("I: inference off", lambda: not robot.inference_on)

    tap(pygame.K_u)
    yield from wait_for("U: motors locked", lambda: robot.motor_lock)
    key(pygame.K_w)
    yield from frames(15)
    results.append((not robot.moving, "locked: W doesn't move her"))
    key(pygame.K_w, False)
    yield from frames(30)       # her /status says LOCKED before U asks for the PIN
    tap(pygame.K_u)
    yield from frames(3)
    typed("1234")
    yield from wait_for("U, PIN 1234: unlocked", lambda: not robot.motor_lock)

    tap(pygame.K_t)
    yield from frames(3)
    typed("hello kida")
    tap(pygame.K_RETURN)
    yield from wait_for("T, typed to her: she answers (her mind panel)", lambda: robot.exchange and robot.exchange["you"] == "hello kida")

    click("EMULATE")
    yield from frames(5)
    results.append((not robot._stop.is_set(), "EMULATE with no robot to go back to: stays emulated"))
    yield from frames(30)
    pygame.image.save(pygame.display.get_surface(), os.path.join(_HERE, "session_test.png"))

    tap(pygame.K_ESCAPE)
    for _ in range(60):
        yield


def main():
    pygame.display.Info = lambda: type("Info", (), {"current_w": W, "current_h": H})()
    import main as controller            # puts scripts/ and controller/scripts/ on the path
    import event_handler
    import fake_kida01

    made = []
    real_fake = fake_kida01.FakeKida01

    class Watched(real_fake):            # the fake main.py starts for EMULATE, kept for the script
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            made.append(self)
    fake_kida01.FakeKida01 = Watched

    real_handle = event_handler.handle_events

    def handle(events, buttons, *a, **k):
        seen["buttons"] = buttons
        return real_handle(events, buttons, *a, **k)
    event_handler.handle_events = handle

    steps = {"gen": None}
    real_get = pygame.event.get

    def get(*a, **k):
        real_get()                       # keep SDL's own queue empty
        if steps["gen"] is None and made:
            steps["gen"] = script(made[0])
        if steps["gen"] is not None:
            try:
                next(steps["gen"])
            except StopIteration:
                queue.append(pygame.event.Event(pygame.QUIT))
        out, queue[:] = list(queue), []
        return out

    pygame.event.get = get
    sys.argv = ["main.py"]
    t0 = time.monotonic()
    controller.run_controller()

    ok = sum(1 for r in results if r[0])
    for good, what in results:
        print(("  ok   " if good else "  FAIL ") + what)
    print(f"{ok} / {len(results)} as expected  ({time.monotonic() - t0:.0f} s)")
    sys.exit(0 if ok == len(results) else 1)


if __name__ == "__main__":
    main()
