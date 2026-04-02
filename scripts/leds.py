import time
import math
import random
import threading
from gpiozero import PWMLED

# BCM pin numbers
LED_PINS = [17, 27]

# Wrapper to maintain your existing interface
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
            self.led.value = self._value  # gpiozero uses 0.0–1.0 directly
        except Exception as e:
            print(f"⚠️ PWMLEDWrapper error: {e}")
            raise

    def on(self):
        self.value = 1.0

    def off(self):
        self.value = 0.0


# Globals
leds = []

led_on = False
effect_on = False
effect_thread = None
stop_effect = False


def setup_leds():
    """Initialize LED objects (safe to call multiple times)."""
    if not leds:
        for pin in LED_PINS:
            leds.append(PWMLEDWrapper(pin))
    for led in leds:
        try:
            led.off()
        except Exception:
            pass


def startup_led_fade():
    duration = 4
    fade_time = 0.02
    steps = int(duration / fade_time)

    for i in range(steps):
        for idx, led in enumerate(leds):
            brightness = (0.5 + 0.5 * math.sin(2 * math.pi * (i / steps) + idx))
            led.value = brightness
        time.sleep(fade_time)

    for led in leds:
        led.off()


def run_chase_effect(duration=15):
    global stop_effect, effect_on, effect_thread

    if effect_on:
        stop_effect = True
        if effect_thread:
            effect_thread.join()
        effect_on = False

    stop_effect = False
    effect_on = True

    effect_thread = threading.Thread(target=_chase_effect)
    effect_thread.start()

    time.sleep(duration)

    stop_effect = True
    effect_thread.join()

    for led in leds:
        led.off()

    effect_on = False
    print("✅ Celebration LEDs off")


def _fade_effect():
    global stop_effect
    while not stop_effect:
        for i in range(101):
            if stop_effect: break
            for led in leds:
                try:
                    led.value = i / 100
                except Exception as e:
                    print(f"⚠️ LED write error in fade effect: {e}")
                    stop_effect = True
                    break
            time.sleep(0.01)
        for i in range(100, -1, -1):
            if stop_effect: break
            for led in leds:
                try:
                    led.value = i / 100
                except Exception as e:
                    print(f"⚠️ LED write error in fade effect: {e}")
                    stop_effect = True
                    break
            time.sleep(0.01)
    for led in leds:
        led.off()


def _strobe_effect():
    global stop_effect
    while not stop_effect:
        for led in leds:
            led.on()
        time.sleep(0.1)
        for led in leds:
            led.off()
        time.sleep(0.1)


def _chase_effect():
    global stop_effect
    while not stop_effect:
        for led in leds:
            if stop_effect:
                break
            led.on()
            time.sleep(0.1)
            led.off()


def _wave_effect():
    global stop_effect
    steps = 100
    while not stop_effect:
        for i in range(steps):
            if stop_effect:
                break
            for idx, led in enumerate(leds):
                brightness = (0.5 + 0.5 * math.sin(2 * math.pi * (i / steps) + idx))
                led.value = brightness
            time.sleep(0.02)
    for led in leds:
        led.off()


def _random_flash_effect():
    global stop_effect
    while not stop_effect:
        led = random.choice(leds)
        led.on()
        time.sleep(0.05)
        led.off()
        time.sleep(0.05)


def toggle_leds():
    global led_on, stop_effect, effect_on, effect_thread

    if effect_on:
        stop_effect = True
        if effect_thread:
            effect_thread.join()
        effect_on = False

    led_on = not led_on

    for led in leds:
        led.on() if led_on else led.off()

    print("💡 LEDs Solid", "ON" if led_on else "OFF")


def toggle_effects():
    global effect_on, stop_effect, effect_thread, led_on

    if effect_on:
        stop_effect = True
        if effect_thread:
            effect_thread.join()
        effect_on = False
        for led in leds:
            led.off()
        print("✨ LED effects OFF")
    else:
        stop_effect = False
        led_on = False
        effect = random.choice([
            _fade_effect,
            _strobe_effect,
            _chase_effect,
            _wave_effect,
            _random_flash_effect
        ])
        effect_thread = threading.Thread(target=effect, daemon=True)
        effect_thread.start()
        effect_on = True
        print(f"✨ LED effects ON → {effect.__name__}")


def start_music_wave():
    global effect_thread, stop_effect, effect_on

    if effect_on:
        stop_effect = True
        if effect_thread:
            effect_thread.join()
        effect_on = False

    stop_effect = False
    effect_thread = threading.Thread(target=_wave_effect, daemon=True)
    effect_thread.start()
    effect_on = True
    print("🎵 LED wave effect started")


def stop_music_wave():
    global stop_effect, effect_thread, effect_on

    stop_effect = True
    if effect_thread:
        effect_thread.join()
        effect_thread = None

    for led in leds:
        led.off()

    effect_on = False
    print("🎵 LED wave effect stopped")