// gamepad.h — the gamepad on this PC, same layout as scripts/joystick_drive.py
//
//   XInput pads (Logitech F710 with its switch on X, Xbox...): full layout
//     left stick   drive (arcade mix -> joy_drive)                 [WASD scheme]
//     LT / RT      left / right track, analog; hold LB / RB to reverse [tank scheme]
//     right stick  aim the servo
//     A photo  B stop  X speed-  Y speed+  Back LIDAR sweep  Start lock/unlock
//     D-pad left/right  previous/next mode (applied after MODE_COMMIT_MS idle)
//     D-pad up          video on/off   (RT too, in the WASD scheme)
//     LB / RB           previous/next mode, in the WASD scheme
//     rumble            whatever the robot's /status "rumble" asks for
//   Anything else (the Generic USB Joystick) through winmm: stick + the
//   first four buttons (trigger/B1/B2/B3 = photo/stop/speed-/speed+).
//
// Sends go through Robot::send, which never blocks; joy_drive is resent every
// HEARTBEAT_MS while the stick is deflected - the robot stops by itself if
// it hears nothing for ~0.8 s.
#pragma once

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <xinput.h>
#include <mmsystem.h>

#include <cmath>
#include <cstdio>
#include <functional>
#include <string>

#include "robot.h"

class Gamepad {
public:
    static constexpr double DEADZONE = 0.08;
    static constexpr double TRIGGER_DEADZONE = 0.05;
    static constexpr DWORD SEND_MS = 50, HEARTBEAT_MS = 250, SERVO_MS = 200, RUMBLE_MS = 250, MODE_COMMIT_MS = 800;
    static constexpr int SERVO_CENTER = 90, SERVO_RANGE = 70, SERVO_STEP = 5;
    static constexpr int MODE_COUNT = 8;

    std::function<void()> onUnlockRequest;   // Start while locked: open the password prompt

    // Name for the HUD ("" = no pad), and a pending mode for it to show (0 = none).
    std::wstring name() const { return name_; }
    int pendingMode() const { return pendingMode_; }

    // Call ~30x a second from the UI thread.
    void poll(Robot& robot, const JValue& status) {
        DWORD now = GetTickCount();
        double l = 0, r = 0;
        bool tank = status["drive_scheme"].text("") == "QAWS";
        std::string mode = status["mode"].text("");

        if (readXInput(now, robot, status, tank, l, r)) {
            // done
        } else if (readWinmm(robot, l, r)) {
            // done
        } else {
            name_.clear();
        }

        if (pendingMode_ && now - pendingAt_ >= MODE_COMMIT_MS) {
            robot.send("mode_" + std::to_string(pendingMode_));
            pendingMode_ = 0;
        }

        // drive: on change, and as a heartbeat while moving
        l = round2(l); r = round2(r);
        bool changed = l != sentL_ || r != sentR_;
        bool moving = l != 0 || r != 0;
        if (now - lastSend_ >= SEND_MS && (changed || (moving && now - lastSend_ >= HEARTBEAT_MS))) {
            char f[80];
            std::snprintf(f, sizeof f, "\"left\":%.2f,\"right\":%.2f", l, r);
            robot.send("joy_drive", f, "joy");
            sentL_ = l; sentR_ = r; lastSend_ = now;
        }

        // servo aim, KEYBOARD/IDLE only (the robot refuses it otherwise anyway)
        if (servoTarget_ != servoSent_ && now - servoAt_ >= SERVO_MS && (mode == "KEYBOARD" || mode == "IDLE")) {
            robot.send("servo_aim", "\"angle\":" + std::to_string(servoTarget_), "servo");
            servoSent_ = servoTarget_;
            servoAt_ = now;
        }
    }

    // Stop the robot and the rumble when the app closes.
    void shutdown(Robot& robot) {
        if (sentL_ != 0 || sentR_ != 0) robot.send("joy_drive", "\"left\":0,\"right\":0", "joy");
        if (xIndex_ >= 0) { XINPUT_VIBRATION v{}; XInputSetState(xIndex_, &v); }
    }

private:
    std::wstring name_;
    int xIndex_ = -1;
    WORD prevButtons_ = 0;
    bool rtDown_ = false;
    int pendingMode_ = 0;
    DWORD pendingAt_ = 0;
    double sentL_ = 0, sentR_ = 0;
    DWORD lastSend_ = 0;
    int servoTarget_ = SERVO_CENTER, servoSent_ = SERVO_CENTER;
    DWORD servoAt_ = 0;
    DWORD rumbleAt_ = 0;
    DWORD winmmButtons_ = 0;
    DWORD lastScan_ = 0;

    static double round2(double v) { return std::round(v * 100.0) / 100.0; }
    static double dz(double v) { return std::fabs(v) < DEADZONE ? 0.0 : v; }

    static void arcade(double turn, double throttleUp, double& l, double& r) {
        double fwd = dz(throttleUp), t = dz(turn);
        l = fwd + t; r = fwd - t;
        double s = std::fmax(1.0, std::fmax(std::fabs(l), std::fabs(r)));
        l /= s; r /= s;
    }

    static int modeNumber(const std::string& m) {
        const char* names[] = {"KEYBOARD", "IR_REMOTE", "AUTONOMOUS", "IDLE", "LINE_FOLLOWER",
                               "WATCHDOG", "LANE_DETECT", "PERSON_FOLLOW"};
        for (int i = 0; i < MODE_COUNT; ++i) if (m == names[i]) return i + 1;
        return 1;
    }

    void stepMode(int step, const std::string& currentMode, DWORD now) {
        int base = pendingMode_ ? pendingMode_ : modeNumber(currentMode);
        pendingMode_ = ((base - 1 + step) % MODE_COUNT + MODE_COUNT) % MODE_COUNT + 1;
        pendingAt_ = now;
    }

    bool readXInput(DWORD now, Robot& robot, const JValue& status, bool tank, double& l, double& r) {
        // (Re)discover a pad at most twice a second - XInputGetState on an empty slot is slow.
        if (xIndex_ < 0 && now - lastScan_ < 500) return false;
        XINPUT_STATE st{};
        if (xIndex_ >= 0 && XInputGetState(xIndex_, &st) != ERROR_SUCCESS) xIndex_ = -1;
        if (xIndex_ < 0) {
            lastScan_ = now;
            for (int i = 0; i < 4; ++i) {
                if (XInputGetState(i, &st) == ERROR_SUCCESS) { xIndex_ = i; prevButtons_ = st.Gamepad.wButtons; break; }
            }
            if (xIndex_ < 0) return false;
        }
        name_ = L"XInput pad " + std::to_wstring(xIndex_ + 1);
        const XINPUT_GAMEPAD& g = st.Gamepad;
        WORD pressed = g.wButtons & ~prevButtons_;
        prevButtons_ = g.wButtons;
        std::string mode = status["mode"].text("");

        if (pressed & XINPUT_GAMEPAD_A) robot.send("photo");
        if (pressed & XINPUT_GAMEPAD_B) robot.send("hard_stop");
        if (pressed & XINPUT_GAMEPAD_X) robot.send("speed_down");
        if (pressed & XINPUT_GAMEPAD_Y) robot.send("speed_up");
        if (pressed & XINPUT_GAMEPAD_BACK) robot.send("lidar_sweep");
        if (pressed & XINPUT_GAMEPAD_DPAD_UP) robot.send("video_toggle");
        if (pressed & XINPUT_GAMEPAD_DPAD_LEFT) stepMode(-1, mode, now);
        if (pressed & XINPUT_GAMEPAD_DPAD_RIGHT) stepMode(1, mode, now);
        if (!tank && (pressed & XINPUT_GAMEPAD_LEFT_SHOULDER)) stepMode(-1, mode, now);
        if (!tank && (pressed & XINPUT_GAMEPAD_RIGHT_SHOULDER)) stepMode(1, mode, now);
        if (pressed & XINPUT_GAMEPAD_START) {
            if (status["motor_lock"].truthy()) { if (onUnlockRequest) onUnlockRequest(); }
            else robot.send("motor_lock_on");
        }

        double lt = g.bLeftTrigger / 255.0, rt = g.bRightTrigger / 255.0;
        if (tank) {
            auto side = [](double v, bool back) {
                v = v < TRIGGER_DEADZONE ? 0.0 : std::fmin(1.0, v);
                return back ? -v : v;
            };
            l = side(lt, g.wButtons & XINPUT_GAMEPAD_LEFT_SHOULDER);
            r = side(rt, g.wButtons & XINPUT_GAMEPAD_RIGHT_SHOULDER);
        } else {
            if (!rtDown_ && rt > 0.6) { rtDown_ = true; robot.send("video_toggle"); }
            else if (rtDown_ && rt < 0.3) rtDown_ = false;
            arcade(g.sThumbLX / 32767.0, g.sThumbLY / 32767.0, l, r);   // XInput: +Y is up (forward)
        }

        double rx = dz(g.sThumbRX / 32767.0);
        servoTarget_ = (int)std::lround((SERVO_CENTER + rx * SERVO_RANGE) / SERVO_STEP) * SERVO_STEP;

        // rumble what the robot asks for (haptics.py), refreshed every RUMBLE_MS
        if (now - rumbleAt_ >= RUMBLE_MS) {
            rumbleAt_ = now;
            const JValue& rb = status["rumble"];
            XINPUT_VIBRATION v{};
            if (robot.connected()) {
                v.wLeftMotorSpeed = (WORD)(std::fmin(1.0, rb["low"].num()) * 65535);
                v.wRightMotorSpeed = (WORD)(std::fmin(1.0, rb["high"].num()) * 65535);
            }
            XInputSetState(xIndex_, &v);
        }
        return true;
    }

    bool readWinmm(Robot& robot, double& l, double& r) {
        JOYINFOEX ji{};
        ji.dwSize = sizeof ji;
        ji.dwFlags = JOY_RETURNALL;
        if (joyGetPosEx(JOYSTICKID1, &ji) != JOYERR_NOERROR) return false;
        JOYCAPSW caps{};
        if (name_.empty() || name_.rfind(L"XInput", 0) == 0) {
            joyGetDevCapsW(JOYSTICKID1, &caps, sizeof caps);
            name_ = caps.szPname[0] ? caps.szPname : L"Joystick";
        }
        DWORD pressed = ji.dwButtons & ~winmmButtons_;
        winmmButtons_ = ji.dwButtons;
        const char* actions[4] = {"photo", "hard_stop", "speed_down", "speed_up"};
        for (int i = 0; i < 4; ++i) if (pressed & (1u << i)) robot.send(actions[i]);
        double x = (ji.dwXpos - 32767.5) / 32767.5, y = (ji.dwYpos - 32767.5) / 32767.5;
        arcade(x, -y, l, r);   // winmm: +Y is down
        return true;
    }
};
