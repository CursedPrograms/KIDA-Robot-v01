# remote_client.py — network bridge between the remote controller and the
# robot's Flask server (scripts/server.py), which already exposes exactly
# what's needed: /status (JSON sensors + mode + power), /video_feed/0 and
# /video_feed/1 (MJPEG), /last_photo, /character_face, and POST /action.
#
# This is the only module in the controller that talks to the network —
# everything else (hud_draw, hud_layout, button_widget) is the same pure
# rendering code the robot uses, fed from the fields this class keeps
# updated.

import io
import threading
import time

import cv2
import numpy as np
import pygame
import requests

import state
from state import DriveMode
from hud_layout import SENSOR_ROWS

STATUS_INTERVAL = 0.5
_LABEL_TO_ATTR  = {label: attr for attr, label in SENSOR_ROWS}


class RemoteClient:
    def __init__(self, base_url: str):
        self.base_url        = base_url.rstrip('/')
        self.frame0           = None   # last decoded cam-0 frame (numpy RGB)
        self.frame1           = None   # last decoded cam-1 frame (numpy RGB)
        self.status           = {}
        self.last_photo_ts    = None
        self.connected        = False
        self._running         = True

        threading.Thread(target=self._poll_status, daemon=True).start()
        threading.Thread(target=self._stream_cam, args=(0,), daemon=True).start()
        threading.Thread(target=self._stream_cam, args=(1,), daemon=True).start()

    def stop(self) -> None:
        self._running = False

    # ── /status polling — mirrors sensor values + mode into state.py, the
    #    exact same module hud_draw.py reads on the robot ──
    def _poll_status(self) -> None:
        import camera_actions
        while self._running:
            try:
                r = requests.get(f"{self.base_url}/status", timeout=1.5)
                data = r.json()
                self.status    = data
                self.connected = True

                mode_name = data.get('mode')
                if mode_name in DriveMode.__members__:
                    state.drive_mode = DriveMode[mode_name]

                for label, value in data.get('sensors', {}).items():
                    attr = _LABEL_TO_ATTR.get(label)
                    if attr:
                        setattr(state, attr, value)

                state.inference_on = data.get('inference_on', False)
                state.motor_lock   = data.get('motor_lock', False)
                state.drive_scheme = data.get('drive_scheme', 'WASD')
                state.bus_v   = data.get('bus_v', 0.0)
                state.cur_ma  = data.get('cur_ma', 0.0)
                state.pwr_w   = data.get('pwr_w', 0.0)
                state.bat_pct = data.get('bat_pct', 0.0)
                camera_actions.active_cam_id = data.get('active_cam_id', 0)

                self.last_photo_ts = data.get('last_photo_ts')
            except Exception:
                self.connected = False
            time.sleep(STATUS_INTERVAL)

    # ── MJPEG stream reader — decode each frame the same RGB numpy array
    #    shape that Picamera2 hands to draw_camera_panel() on the robot ──
    def _stream_cam(self, cam_id: int) -> None:
        url = f"{self.base_url}/video_feed/{cam_id}"
        while self._running:
            try:
                resp = requests.get(url, stream=True, timeout=5)
                buf  = b""
                for chunk in resp.iter_content(chunk_size=4096):
                    if not self._running:
                        return
                    buf  += chunk
                    start = buf.find(b'\xff\xd8')
                    end   = buf.find(b'\xff\xd9')
                    if start != -1 and end != -1 and end > start:
                        jpg = buf[start:end + 2]
                        buf = buf[end + 2:]
                        arr = np.frombuffer(jpg, dtype=np.uint8)
                        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                        if img is not None:
                            # server.py encodes frames as RGB2BGR before
                            # JPEG; undo that so we get the same array
                            # ui.py's Picamera2 capture would have produced.
                            frame = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                            if cam_id == 0:
                                self.frame0 = frame
                            else:
                                self.frame1 = frame
            except Exception:
                time.sleep(1.0)

    # ── static images (last photo, character face) ──
    def fetch_image(self, path: str):
        """GET an image endpoint and return a pygame Surface, or None."""
        try:
            r = requests.get(f"{self.base_url}{path}", timeout=3)
            if r.status_code != 200 or not r.content:
                return None
            return pygame.image.load(io.BytesIO(r.content))
        except Exception:
            return None

    # ── outbound commands ──
    def send_action(self, command: str, password: str | None = None, **fields) -> bool:
        """fields: extra JSON keys, e.g. left/right for 'joy_drive'."""
        payload = {"command": command, **fields}
        if password is not None:
            payload["password"] = password
        try:
            r = requests.post(f"{self.base_url}/action", json=payload, timeout=2)
            if not r.ok:
                return False
            return bool(r.json().get("ok", False))
        except Exception:
            return False
