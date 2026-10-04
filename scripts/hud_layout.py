# hud_layout.py — shared HUD geometry + sensor-row config for KIDA
#
# Pure layout math, no pygame surfaces, no hardware calls. Used by both the
# on-robot HUD (ui.py) and the remote controller (controller/main.py) so a
# layout change made once applies to both screens identically.

import pygame

CAM_PAD    = 12
CAM_H_FRAC = 0.40   # fraction of screen height used by the camera row

SEN_X1_OFFSET  = 14
SEN_X2_OFFSET  = 280
SEN_TOP_OFFSET = 62   # below the three status rows (power, status, hints)

BTN_PANEL_WIDTH = 320

# (state attr name, display label) — order here is the order drawn in the
# sensor grid. server.py's /status route keys its "sensors" dict by label,
# so the controller maps label -> attr using this same list.
SENSOR_ROWS = [
    ("photoValue",       "Photo"),
    ("uvValue",          "UV"),
    ("metalValue",       "Metal"),
    ("ballSwitchValue",  "Ball Sw"),
    ("motionValue",      "Motion"),
    ("lfLeftValue",      "LF L"),
    ("lfMidValue",       "LF M"),
    ("lfRightValue",     "LF R"),
    ("laserValue",       "Laser"),
    ("ultrasonic0Value", "US0"),
    ("ultrasonic1Value", "US1"),
    ("mpu_ax",           "AX"),
    ("mpu_ay",           "AY"),
    ("mpu_az",           "AZ"),
    ("mpu_gx",           "GX"),
    ("mpu_gy",           "GY"),
    ("mpu_gz",           "GZ"),
    ("systemStatus",     "Status"),
]


def compute_layout(sw: int, sh: int) -> dict:
    """
    Four equal-size panels in a row, left to right: character face, cam-1,
    cam-0, last photo. All four share the same width and height.
    """
    cam_top = CAM_PAD
    cam_h   = int(sh * CAM_H_FRAC)
    face_w  = (sw - CAM_PAD * 5) // 4
    cam_w   = face_w

    face_rect  = pygame.Rect(CAM_PAD,                          cam_top, face_w, cam_h)
    cam1_rect  = pygame.Rect(CAM_PAD * 2 + face_w,             cam_top, cam_w,  cam_h)
    cam0_rect  = pygame.Rect(CAM_PAD * 3 + face_w + cam_w,     cam_top, cam_w,  cam_h)
    photo_rect = pygame.Rect(CAM_PAD * 4 + face_w + cam_w * 2, cam_top, cam_w,  cam_h)

    hud_y    = cam_top + cam_h + CAM_PAD
    hud_h    = sh - hud_y
    hud_rect = pygame.Rect(0, hud_y, sw, hud_h)

    sen_x1  = SEN_X1_OFFSET
    sen_x2  = sen_x1 + SEN_X2_OFFSET
    sen_top = hud_y + SEN_TOP_OFFSET

    btn_panel_x    = sw - BTN_PANEL_WIDTH
    btn_panel_rect = pygame.Rect(btn_panel_x - 6, hud_y + 2,
                                  sw - btn_panel_x + 4, hud_h - 4)

    return {
        "face_rect":      face_rect,
        "cam1_rect":      cam1_rect,
        "cam0_rect":      cam0_rect,
        "photo_rect":     photo_rect,
        "hud_y":          hud_y,
        "hud_h":          hud_h,
        "hud_rect":       hud_rect,
        "sen_x1":         sen_x1,
        "sen_x2":         sen_x2,
        "sen_top":        sen_top,
        "btn_panel_x":    btn_panel_x,
        "btn_panel_rect": btn_panel_rect,
    }
