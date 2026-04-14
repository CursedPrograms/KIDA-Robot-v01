# uv_follow.py — chase a UV light source
#
# Reads state.uvValue (written by arduino.py from "UV:..." sensor lines).
# Sends FORWARD to dev00 when the UV reading is above the threshold,
# STOP otherwise.  Only transmits when the command changes.

import time
from arduino import send_command
import state

UV_THRESHOLD  = 100     # ADC counts — tune for your sensor
POLL_INTERVAL = 0.2     # seconds between reads
DEVICE        = "dev00" # motor Arduino


def uv_follow_loop(poll_interval: float = POLL_INTERVAL) -> None:
    last_command = None

    while True:
        # state.uvValue is written as a string by arduino.py; cast safely
        try:
            uv_value = int(getattr(state, "uvValue", 0))
        except (ValueError, TypeError):
            uv_value = 0

        command = "FORWARD" if uv_value > UV_THRESHOLD else "STOP"

        if command != last_command:
            print(f"[UV Follow] UV={uv_value}  →  {command}")
            send_command(DEVICE, command)
            last_command = command

        time.sleep(poll_interval)


if __name__ == "__main__":
    try:
        uv_follow_loop()
    except KeyboardInterrupt:
        print("UV follow stopped.")
