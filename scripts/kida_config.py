#!/usr/bin/env python3
"""
kida_config.py — her settings from config.json, with today's set-up as the defaults.

    import kida_config
    cams = kida_config.cameras()     # {"NightCamPort": 0, "NightCamSide": "left", ...}

config.json "Config" / "Cameras" (all optional; options.py, her web page /options
and the PC controller's Options button all edit it):
    NightCamPort     0        the night cam's Pi camera port (CAM/DISP 0); the AI cam
                              finds itself (the IMX500 knows its own port)
    NightCamSide     "left"   which side of her face the night cam is; the AI cam is
                              the other side. They overlap in the centre.
    NightCamHFovDeg  62.2     the night cam's horizontal field of view
    AICamHFovDeg     66.3     the AI Camera's (IMX500)
    BaselineCm       8.0      lens to lens, for the stereo distance to a person
    InvertSteer      false    flip if person follow turns away from you
A change takes effect when she restarts.
"""

import json
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(_ROOT, "config.json")

CAMERAS = {
    "NightCamPort":    0,
    "NightCamSide":    "left",
    "NightCamHFovDeg": 62.2,
    "AICamHFovDeg":    66.3,
    "BaselineCm":      8.0,
    "InvertSteer":     False,
}


def section(name: str, defaults: dict) -> dict:
    """config.json Config/<name> over the defaults (a missing or broken file gives the defaults)."""
    out = dict(defaults)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            out.update(json.load(f)["Config"].get(name, {}))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return out


def cameras() -> dict:
    cams = section("Cameras", CAMERAS)
    side = str(cams.get("NightCamSide", "left")).lower()
    cams["NightCamSide"] = side if side in ("left", "right") else "left"
    try:
        cams["NightCamPort"] = int(cams["NightCamPort"])
    except (TypeError, ValueError):
        cams["NightCamPort"] = CAMERAS["NightCamPort"]
    for k in ("NightCamHFovDeg", "AICamHFovDeg", "BaselineCm"):
        try:
            cams[k] = float(cams[k])
        except (TypeError, ValueError):
            cams[k] = CAMERAS[k]
    cams["InvertSteer"] = bool(cams.get("InvertSteer"))
    return cams
