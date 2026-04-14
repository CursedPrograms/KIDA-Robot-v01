# leds.py — PWM LED control for KIDA
#
# Fixes vs original:
#   • run_chase_effect() no longer blocks the calling thread — it starts
#     the effect and returns immediately.  Call stop_effects() or
#     toggle_leds() to end it.
#   • stop_effect is now a threading.Event (set/clear/is_set) instead of a
#     bare bool — no race between the writer and the reader thread.
#   • ALL effect threads are started as daemon=True so they never prevent
#     a clean process exit.
#   • Effect-stopping helper _stop_current_effect() is deduplicated — was
#     copy-pasted in 5 places.

import time
import math
import random
import threading
from gpiozero import PWMLED

LED_PINS = [17, 27]


class PWMLEDWrapper:
    def __init__(self, pin, frequency=100):
        self.pin = pin
        self.led = PWMLED(pin, frequency=frequency)
        self._value = 0.0

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, v):
        self._value = max(0.0, min(1.0, v))
        try:
            self.led.value = self._value
        except Exception as e:
            print(f"⚠️ PWMLEDWrapper error pin {self.pin}: {e}")
            raise

    def on(self):
        self.value = 1.0

    def off(self):
        self.value = 0.0


# ── Module-level state ──────────────────────────────────────────────────────
leds: list[PWMLEDWrapper] = []

led_on        = False
effect_on     = False
effect_thread: threading.Thread | None = None
_stop_event   = threading.Event()   # replaces bare bool stop_effect


# ── Helpers ─────────────────────────────────────────────────────────────────

def _all_off() -> None:
    for led in leds:
        try:
            led.off()
        except Exception:
            pass


def _stop_current_effect() -> None:
    """Signal the running effect thread to stop and wait for it to finish."""
    global effect_on, effect_thread
    if not effect_on:
        return
    _stop_event.set()
    if effect_thread and effect_thread.is_alive():
        effect_thread.join(timeout=2.0)
    effect_on    = False
    effect_thread = None


def _start_effect(target) -> None:
    global effect_on, effect_thread
    _stop_current_effect()
    _stop_event.clear()
    effect_thread = threading.Thread(target=target, daemon=True)
    effect_thread.start()
    effect_on = True


# ── Public setup ─────────────────────────────────────────────────────────────

def setup_leds() -> None:
    """Initialize LED objects.  Safe to call multiple times."""
    if not leds:
        for pin in LED_PINS:
            leds.append(PWMLEDWrapper(pin))
    _all_off()


def startup_led_fade() -> None:
    duration   = 4
    fade_time  = 0.02
    steps      = int(duration / fade_time)
    for i in range(steps):
        for idx, led in enumerate(leds):
            led.value = 0.5 + 0.5 * math.sin(2 * math.pi * (i / steps) + idx)
        time.sleep(fade_time)
    _all_off()


# ── Public controls ───────────────────────────────────────────────────────────

def toggle_leds() -> None:
    """Toggle all LEDs solid on/off.  Stops any running effect first."""
    global led_on
    _stop_current_effect()
    _all_off()
    led_on = not led_on
    if led_on:
        for led in leds:
            led.on()
    print("💡 LEDs Solid", "ON" if led_on else "OFF")


def toggle_effects() -> None:
    """Start a random effect, or stop the current one."""
    global led_on
    if effect_on:
        _stop_current_effect()
        _all_off()
        print("✨ LED effects OFF")
    else:
        led_on = False
        _all_off()
        effect = random.choice([
            _fade_effect,
            _strobe_effect,
            _chase_effect,
            _wave_effect,
            _random_flash_effect,
        ])
        _start_effect(effect)
        print(f"✨ LED effects ON → {effect.__name__}")


def run_chase_effect() -> None:
    """
    Start the chase effect in the background and return immediately.
    (Previously blocked for `duration` seconds — that deadlocked the UI.)
    Call stop_effects() or toggle_leds() to end it.
    """
    _start_effect(_chase_effect)
    print("🎉 Chase effect started")


def stop_effects() -> None:
    """Stop whatever effect is running and turn all LEDs off."""
    _stop_current_effect()
    _all_off()
    print("✅ LED effects stopped")


def start_music_wave() -> None:
    _start_effect(_wave_effect)
    print("🎵 LED wave effect started")


def stop_music_wave() -> None:
    _stop_current_effect()
    _all_off()
    print("🎵 LED wave effect stopped")


# ── Effect implementations ───────────────────────────────────────────────────
# Each loops until _stop_event is set, then turns all LEDs off and returns.

def _fade_effect() -> None:
    while not _stop_event.is_set():
        for i in range(101):
            if _stop_event.is_set():
                break
            for led in leds:
                try:
                    led.value = i / 100
                except Exception as e:
                    print(f"⚠️ LED fade error: {e}")
                    _stop_event.set()
                    break
            time.sleep(0.01)
        for i in range(100, -1, -1):
            if _stop_event.is_set():
                break
            for led in leds:
                try:
                    led.value = i / 100
                except Exception as e:
                    print(f"⚠️ LED fade error: {e}")
                    _stop_event.set()
                    break
            time.sleep(0.01)
    _all_off()


def _strobe_effect() -> None:
    while not _stop_event.is_set():
        for led in leds:
            led.on()
        time.sleep(0.1)
        for led in leds:
            led.off()
        time.sleep(0.1)
    _all_off()


def _chase_effect() -> None:
    while not _stop_event.is_set():
        for led in leds:
            if _stop_event.is_set():
                break
            led.on()
            time.sleep(0.1)
            led.off()
    _all_off()


def _wave_effect() -> None:
    steps = 100
    while not _stop_event.is_set():
        for i in range(steps):
            if _stop_event.is_set():
                break
            for idx, led in enumerate(leds):
                led.value = 0.5 + 0.5 * math.sin(2 * math.pi * (i / steps) + idx)
            time.sleep(0.02)
    _all_off()


def _random_flash_effect() -> None:
    while not _stop_event.is_set():
        led = random.choice(leds)
        led.on()
        time.sleep(0.05)
        led.off()
        time.sleep(0.05)
    _all_off()
