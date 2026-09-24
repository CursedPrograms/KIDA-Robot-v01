// main.cpp — KIDA Remote Controller, native Windows build
//
// The C++ twin of controller/main.py: the same HUD (four panels — KIDA's
// face, cam-1, cam-0, last photo — then the status strip, sensor grid and a
// CONTROLS button panel), the same keys, the same gamepad layout, talking to
// the same Flask server (scripts/server.py). Pure Win32: WinHTTP for the
// network, WIC for JPEGs, GDI for drawing, XInput/winmm for pads — so the
// .exe needs no DLLs beyond what ships with Windows.
//
// Robot address, first match wins:
//   KIDA-Controller.exe 192.168.1.50            (port 5004)
//   KIDA-Controller.exe http://192.168.1.50:5004
//   ROBOT_URL environment variable
//   kida_controller.ini next to the .exe (written after you type it once)
//   otherwise the window asks for it.
//
// Keys (KEYBOARD mode; IDLE too, where a drive key wakes her):
//   WASD scheme  W/S drive, A/D rotate, W+A / W+D / S+A / S+D curve while driving
//   QAWS scheme  Q/A left track fwd/back, W/S right track fwd/back
//   1-8 mode  Space stop  X speed  I inference  M music  L LEDs  K effects
//   U lock/unlock  C photo  V video  , / . scheme WASD / QAWS  Esc quit (Q too, in WASD)
//   T type to KIDA (her answer shows in the MIND panel)  H go home

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <windowsx.h>
#include <shellapi.h>

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <memory>
#include <set>
#include <string>
#include <vector>

#include "gamepad.h"
#include "image.h"
#include "json.h"
#include "net.h"
#include "robot.h"

namespace {

constexpr UINT WM_UNLOCK_RESULT = WM_APP + 1;
constexpr UINT_PTR TICK_TIMER = 1;
constexpr int TICK_MS = 33;
constexpr DWORD KEY_HEARTBEAT_MS = 300;   // the robot stops a held drive it hasn't heard about for ~0.8 s
constexpr int DEFAULT_PORT = 5004;

// ── layout, exactly scripts/hud_layout.py ──
constexpr int CAM_PAD = 12;
constexpr double CAM_H_FRAC = 0.40;
constexpr int SEN_X1_OFFSET = 14, SEN_X2_OFFSET = 280, SEN_TOP_OFFSET = 64;   // below the 3 status rows (GDI fonts sit taller than pygame's)
constexpr int BTN_PANEL_WIDTH = 320;

const char* SENSOR_LABELS[] = {"Photo", "UV", "Metal", "Ball Sw", "Motion", "LF L", "LF M", "LF R", "Laser",
                               "US0", "US1", "AX", "AY", "AZ", "GX", "GY", "GZ", "Status"};

struct ModeStyle { const char* name; const wchar_t* label; COLORREF color; };
const ModeStyle MODE_STYLES[] = {
    {"KEYBOARD", L"KB", RGB(100, 220, 140)},     {"IR_REMOTE", L"IR", RGB(100, 180, 255)},
    {"AUTONOMOUS", L"AUTO", RGB(255, 190, 80)},  {"LINE_FOLLOWER", L"LF", RGB(200, 100, 255)},
    {"WATCHDOG", L"WATCH", RGB(255, 80, 80)},    {"LANE_DETECT", L"LANE", RGB(80, 208, 255)},
    {"PERSON_FOLLOW", L"FOLLOW", RGB(120, 255, 200)}, {"IDLE", L"IDLE", RGB(180, 80, 80)},
};

struct Button {
    std::wstring label;
    COLORREF color;
    std::string command;      // sent on click, unless special
    enum Special { None, Lock, Scheme, Camera, Play, Chat } special = None;
    RECT rect{};
};

// ── app state (UI thread only) ──
HWND g_hwnd = nullptr;
std::unique_ptr<Robot> g_robot;
Gamepad g_pad;
JValue g_status, g_mind;
std::vector<Button> g_buttons;
std::set<int> g_keys;              // held drive keys (virtual-key codes)
DWORD g_lastKeyBeat = 0;
POINT g_mouse{-1, -1};
bool g_mouseDown = false;

HFONT g_fSm, g_fXs, g_fHd, g_fNoSig, g_fBtn;

enum class Prompt { None, Unlock, Address, Chat };
Prompt g_prompt = Prompt::None;
std::wstring g_promptText;
std::wstring g_promptError;
bool g_unlockPending = false;
bool g_swallowChar = false;        // the key that opened a prompt mustn't also type into it

// ── helpers ─────────────────────────────────────────────────────────────
COLORREF shade(COLORREF c, int d) {
    auto f = [d](int v) { return std::max(0, std::min(255, v + d)); };
    return RGB(f(GetRValue(c)), f(GetGValue(c)), f(GetBValue(c)));
}

void fillRect(HDC dc, const RECT& r, COLORREF c) {
    HBRUSH b = CreateSolidBrush(c);
    FillRect(dc, &r, b);
    DeleteObject(b);
}

void frameRect(HDC dc, const RECT& r, COLORREF c, int width) {
    HPEN p = CreatePen(PS_INSIDEFRAME, width, c);
    HGDIOBJ op = SelectObject(dc, p), ob = SelectObject(dc, GetStockObject(NULL_BRUSH));
    Rectangle(dc, r.left, r.top, r.right, r.bottom);
    SelectObject(dc, op); SelectObject(dc, ob);
    DeleteObject(p);
}

void roundRect(HDC dc, const RECT& r, COLORREF fill, COLORREF border, int radius, int bw = 1) {
    HBRUSH b = CreateSolidBrush(fill);
    HPEN p = CreatePen(PS_INSIDEFRAME, bw, border);
    HGDIOBJ ob = SelectObject(dc, b), op = SelectObject(dc, p);
    RoundRect(dc, r.left, r.top, r.right, r.bottom, radius * 2, radius * 2);
    SelectObject(dc, ob); SelectObject(dc, op);
    DeleteObject(b); DeleteObject(p);
}

// Darken a region by `alpha` (0..255) — the translucent overlays.
void dim(HDC dc, const RECT& r, BYTE alpha) {
    HDC mem = CreateCompatibleDC(dc);
    BITMAPINFO bi{};
    bi.bmiHeader.biSize = sizeof bi.bmiHeader;
    bi.bmiHeader.biWidth = 1; bi.bmiHeader.biHeight = 1; bi.bmiHeader.biPlanes = 1; bi.bmiHeader.biBitCount = 32;
    void* bits = nullptr;
    HBITMAP bmp = CreateDIBSection(dc, &bi, DIB_RGB_COLORS, &bits, nullptr, 0);
    *(DWORD*)bits = 0;   // black
    HGDIOBJ old = SelectObject(mem, bmp);
    BLENDFUNCTION bf{AC_SRC_OVER, 0, alpha, 0};
    AlphaBlend(dc, r.left, r.top, r.right - r.left, r.bottom - r.top, mem, 0, 0, 1, 1, bf);
    SelectObject(mem, old);
    DeleteObject(bmp);
    DeleteDC(mem);
}

int text(HDC dc, int x, int y, const std::wstring& s, COLORREF c, HFONT f) {
    HGDIOBJ old = SelectObject(dc, f);
    SetTextColor(dc, c);
    TextOutW(dc, x, y, s.c_str(), (int)s.size());
    SIZE sz{};
    GetTextExtentPoint32W(dc, s.c_str(), (int)s.size(), &sz);
    SelectObject(dc, old);
    return sz.cx;
}

void textCentered(HDC dc, const RECT& r, const std::wstring& s, COLORREF c, HFONT f) {
    HGDIOBJ old = SelectObject(dc, f);
    SetTextColor(dc, c);
    RECT rr = r;
    DrawTextW(dc, s.c_str(), (int)s.size(), &rr, DT_CENTER | DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX);
    SelectObject(dc, old);
}

void drawImage(HDC dc, const RECT& r, const ImagePtr& img) {
    BITMAPINFO bi{};
    bi.bmiHeader.biSize = sizeof bi.bmiHeader;
    bi.bmiHeader.biWidth = img->w;
    bi.bmiHeader.biHeight = -img->h;     // top-down
    bi.bmiHeader.biPlanes = 1;
    bi.bmiHeader.biBitCount = 32;
    SetStretchBltMode(dc, HALFTONE);
    SetBrushOrgEx(dc, 0, 0, nullptr);
    StretchDIBits(dc, r.left, r.top, r.right - r.left, r.bottom - r.top, 0, 0, img->w, img->h,
                  img->bgra.data(), &bi, DIB_RGB_COLORS, SRCCOPY);
}

std::wstring fmt(const char* f, double v) {
    char b[64];
    std::snprintf(b, sizeof b, f, v);
    return widen(b);
}

// ── robot address ───────────────────────────────────────────────────────
std::wstring iniPath() {
    wchar_t exe[MAX_PATH];
    GetModuleFileNameW(nullptr, exe, MAX_PATH);
    std::wstring p = exe;
    return p.substr(0, p.find_last_of(L"\\/") + 1) + L"kida_controller.ini";
}

bool parseAddress(std::string s, std::string& host, int& port) {
    auto trim = [](std::string& v) {
        while (!v.empty() && isspace((unsigned char)v.back())) v.pop_back();
        while (!v.empty() && isspace((unsigned char)v.front())) v.erase(v.begin());
    };
    trim(s);
    if (s.rfind("http://", 0) == 0) s = s.substr(7);
    if (!s.empty() && s.back() == '/') s.pop_back();
    if (s.empty()) return false;
    port = DEFAULT_PORT;
    size_t c = s.rfind(':');
    if (c != std::string::npos) {
        port = std::atoi(s.substr(c + 1).c_str());
        s = s.substr(0, c);
        if (port <= 0 || port > 65535) return false;
    }
    host = s;
    return !host.empty();
}

std::string savedAddress() {
    std::ifstream f(iniPath().c_str());
    std::string line;
    while (std::getline(f, line)) {
        if (line.rfind("robot=", 0) == 0) return line.substr(6);
    }
    return "";
}

void saveAddress(const std::string& addr) {
    std::ofstream f(iniPath().c_str(), std::ios::trunc);
    f << "; KIDA Remote Controller — robot address (IP, IP:port or http://IP:port)\n";
    f << "robot=" << addr << "\n";
}

bool connectTo(const std::string& addr) {
    std::string host;
    int port;
    if (!parseAddress(addr, host, port)) return false;
    g_robot = std::make_unique<Robot>(host, port);
    g_robot->start();
    std::wstring title = L"KIDA — Remote Controller (" + widen(g_robot->address()) + L")";
    SetWindowTextW(g_hwnd, title.c_str());
    return true;
}

// ── buttons (controller/scripts/buttons.py + lock + scheme) ─────────────
void createButtons() {
    const COLORREF pink = RGB(255, 182, 193), blue = RGB(160, 200, 255), purple = RGB(200, 160, 255),
                   red = RGB(255, 140, 140);
    g_buttons = {
        {L"Take Photo", pink, "photo"},
        {L"Cam: 0", blue, "camera_switch", Button::Camera},
        {L"Save Inference", pink, "save_inference"},
        {L"Record Video", pink, "video_start"},
        {L"Keyboard Mode", blue, "mode_1"},
        {L"Autonomous", blue, "mode_3"},
        {L"Line Follow", purple, "mode_5"},
        {L"Idle / Stop", blue, "mode_4"},
        {L"Watchdog", red, "mode_6"},
        {L"Follow Person", purple, "mode_8"},
        {L"Play Music", pink, "music_play", Button::Play},
        {L"Next Track", pink, "music_skip"},
        {L"Stop Music", pink, "music_stop"},
        {L"Toggle LEDs", pink, "leds_toggle"},
        {L"Go Home", blue, "go_home"},
        {L"Type to KIDA", RGB(160, 200, 220), "", Button::Chat},
        {L"Lock Motors", RGB(140, 200, 140), "", Button::Lock},
        {L"Scheme: WASD", RGB(160, 160, 220), "", Button::Scheme},
    };
}

bool buttonEnabled(const Button& b) {
    return !(b.special == Button::Play && g_status["music_on"].truthy());
}

void openUnlock() {
    g_prompt = Prompt::Unlock;
    g_promptText.clear();
    g_promptError.clear();
}

void openChat() {
    g_prompt = Prompt::Chat;
    g_promptText.clear();
    g_promptError.clear();
}

void lockClick() {
    if (!g_robot) return;
    if (g_status["motor_lock"].truthy()) openUnlock();
    else g_robot->send("motor_lock_on");
}

void clickButton(const Button& b) {
    if (!g_robot || !buttonEnabled(b)) return;
    if (b.special == Button::Lock) return lockClick();
    if (b.special == Button::Chat) return openChat();
    if (b.special == Button::Scheme) {
        g_robot->send(g_status["drive_scheme"].text("WASD") == "WASD" ? "scheme_qaws" : "scheme_wasd");
        return;
    }
    g_robot->send(b.command);
}

// ── keyboard driving (same rule as scripts/drive_mix.py) ────────────────
bool driveAllowed() {
    std::string m = g_status["mode"].text("");
    return m == "KEYBOARD" || m == "IDLE";     // IDLE: a drive key is what wakes her
}

bool tankScheme() { return g_status["drive_scheme"].text("WASD") == "QAWS"; }

void sendKeyDrive() {
    if (!g_robot) return;
    g_lastKeyBeat = GetTickCount();
    auto held = [](int vk) { return g_keys.count(vk) > 0; };
    if (tankScheme()) {
        const char* l = held('Q') ? "left_forward" : held('A') ? "left_backward" : "left_stop";
        const char* r = held('W') ? "right_forward" : held('S') ? "right_backward" : "right_stop";
        g_robot->send(l, "", "left");
        g_robot->send(r, "", "right");
        return;
    }
    int throttle = (held('W') ? 1 : 0) - (held('S') ? 1 : 0);
    int turn = (held('D') ? 1 : 0) - (held('A') ? 1 : 0);
    if (throttle && turn) {
        g_robot->send("move_curve", "\"throttle\":" + std::to_string(throttle) + ",\"turn\":" + std::to_string(turn), "main");
    } else if (throttle) {
        g_robot->send(throttle > 0 ? "move_forward" : "move_backward", "", "main");
    } else if (turn) {
        g_robot->send(turn > 0 ? "move_right" : "move_left", "", "main");
    } else {
        g_robot->send("move_stop", "", "main");
    }
}

bool isDriveKey(int vk) {
    if (tankScheme()) return vk == 'Q' || vk == 'A' || vk == 'W' || vk == 'S';
    return vk == 'W' || vk == 'A' || vk == 'S' || vk == 'D';
}

void releaseAllDriveKeys() {
    if (g_keys.empty()) return;
    g_keys.clear();
    sendKeyDrive();
}

void onKeyDownImpl(int vk);

void onKeyDown(int vk) {
    Prompt before = g_prompt;
    onKeyDownImpl(vk);
    if (before == Prompt::None && g_prompt != Prompt::None) g_swallowChar = true;
}

void onKeyDownImpl(int vk) {
    if (g_prompt != Prompt::None) {
        if (vk == VK_ESCAPE) {
            if (g_prompt == Prompt::Address && !g_robot) { PostMessageW(g_hwnd, WM_CLOSE, 0, 0); return; }
            g_prompt = Prompt::None;
        } else if (vk == VK_BACK) {
            if (!g_promptText.empty()) g_promptText.pop_back();
            g_promptError.clear();
        } else if (vk == VK_RETURN) {
            if (g_prompt == Prompt::Chat) {
                if (g_robot && !g_promptText.empty())
                    g_robot->send("chat", "\"text\":" + jsonQuote(narrow(g_promptText)));
                g_prompt = Prompt::None;
            } else if (g_prompt == Prompt::Address) {
                std::string addr = narrow(g_promptText);
                if (connectTo(addr)) { saveAddress(addr); g_prompt = Prompt::None; }
                else g_promptError = L"That doesn't look like an address";
            } else if (g_robot && !g_unlockPending) {
                g_unlockPending = true;
                g_robot->send("motor_lock_off", "\"password\":" + jsonQuote(narrow(g_promptText)), "",
                              [](bool ok) { PostMessageW(g_hwnd, WM_UNLOCK_RESULT, ok ? 1 : 0, 0); });
            }
        }
        return;
    }
    if (!g_robot) return;

    if (isDriveKey(vk)) {
        if (driveAllowed()) { g_keys.insert(vk); sendKeyDrive(); }
        return;
    }
    if (vk >= '1' && vk <= '8') { g_robot->send("mode_" + std::string(1, (char)vk)); return; }
    switch (vk) {
        case VK_ESCAPE: PostMessageW(g_hwnd, WM_CLOSE, 0, 0); break;
        case 'Q': PostMessageW(g_hwnd, WM_CLOSE, 0, 0); break;     // (in QAWS, Q drives instead — above)
        case VK_SPACE: g_robot->send("hard_stop"); break;
        case 'X': g_robot->send("speed_cycle"); break;
        case 'I': g_robot->send("inference_toggle"); break;
        case 'M': g_robot->send(g_status["music_on"].truthy() ? "music_skip" : "music_play"); break;
        case 'L': g_robot->send("leds_toggle"); break;
        case 'K': g_robot->send("leds_effects_toggle"); break;
        case 'U': lockClick(); break;
        case 'C': g_robot->send("photo"); break;
        case 'T': openChat(); break;
        case 'H': g_robot->send("go_home"); break;
        case 'V': g_robot->send("video_start"); break;
        case VK_OEM_COMMA: g_robot->send("scheme_wasd"); break;
        case VK_OEM_PERIOD: g_robot->send("scheme_qaws"); break;
    }
}

void onKeyUp(int vk) {
    if (g_keys.erase(vk)) sendKeyDrive();   // release W from W+A: she keeps turning
}

// ── drawing ─────────────────────────────────────────────────────────────
void drawPanel(HDC dc, const RECT& r, const ImagePtr& img, const std::wstring& label) {
    if (img && !img->empty()) {
        drawImage(dc, r, img);
    } else {
        roundRect(dc, r, RGB(8, 10, 18), RGB(50, 70, 110), 6);
        textCentered(dc, r, L"[ " + label + L" — NO SIGNAL ]", RGB(60, 75, 100), g_fNoSig);
    }
    frameRect(dc, r, RGB(50, 72, 115), 2);
    text(dc, r.left + 6, r.top + 5, label, RGB(150, 185, 255), g_fXs);
}

void drawStatus(HDC dc, int hudY, int x) {
    const JValue& s = g_status;
    double busV = s["bus_v"].num(), curMa = s["cur_ma"].num(), pwrW = s["pwr_w"].num(), bat = s["bat_pct"].num();
    char b[256];
    std::snprintf(b, sizeof b, "  PWR %.2fV  %.3fA  %.2fW  BAT %.0f%%", busV, curMa / 1000.0, pwrW, bat);
    text(dc, x, hudY + 6, widen(b), RGB(70, 215, 100), g_fSm);

    std::wstring line = L"  Spd:" + widen(s["motor_speed"].text("-")) + L"  T:" + widen(s["cpu_temp"].text("N/A"))
                        + L"  CPU:" + fmt("%.0f", s["cpu"].num()) + L"%  RAM:" + fmt("%.0f", s["ram"].num())
                        + L"%  IP:" + widen(s["ip"].text(g_robot ? g_robot->address().c_str() : "-"))
                        + L"  Inf:" + (s["inference_on"].truthy() ? L"ON" : L"off")
                        + L"  Mus:" + (s["music_on"].truthy() ? L">" : L"#") + L"  Mode:";
    int w = text(dc, x, hudY + 24, line, RGB(160, 190, 235), g_fSm);
    std::string mode = s["mode"].text("");
    const wchar_t* ml = L"???";
    COLORREF mc = RGB(200, 200, 200);
    for (const auto& m : MODE_STYLES) if (mode == m.name) { ml = m.label; mc = m.color; }
    text(dc, x + w, hudY + 24, std::wstring(L" [") + ml + L"]", mc, g_fSm);

    int hw = text(dc, x, hudY + 42, L"  1=KB  2=IR  3=AUTO  4=IDLE  5=LINE  6=WATCH  7=LANE  8=FOLLOW", RGB(80, 100, 140), g_fXs);
    std::wstring pad = g_pad.name();
    std::wstring padText = pad.empty() ? L"  pad: none" : L"  pad: " + pad.substr(0, 28);
    if (!pad.empty() && g_pad.pendingMode()) padText += L"  -> mode " + std::to_wstring(g_pad.pendingMode()) + L"...";
    int pw = text(dc, x + hw + 12, hudY + 42, padText, pad.empty() ? RGB(90, 90, 110) : RGB(100, 220, 140), g_fXs);
    if (!g_mind.isNull() && !g_mind["mood"].isNull()) {
        std::wstring mood = L"  mind: " + widen(g_mind["mood"]["label"].text("?")) + (g_mind["sleeping"].truthy() ? L" (asleep)" : L"");
        text(dc, x + hw + 12 + pw + 8, hudY + 42, mood, RGB(200, 160, 235), g_fXs);
    }
}

void drawSensors(HDC dc, int x1, int x2, int top) {
    const JValue& sensors = g_status["sensors"];
    const int n = (int)(sizeof SENSOR_LABELS / sizeof SENSOR_LABELS[0]);
    const int mid = (n + 1) / 2;
    for (int i = 0; i < n; ++i) {
        int col = i < mid ? 0 : 1, row = i < mid ? i : i - mid;
        int x = x1 + col * (x2 - x1), y = top + row * 19;
        text(dc, x, y, widen(SENSOR_LABELS[i]) + L":", RGB(100, 130, 185), g_fXs);
        std::string v = sensors[SENSOR_LABELS[i]].text("-");
        if (v.size() > 30) v = v.substr(0, 30);
        text(dc, x + 88, y, widen(v), RGB(215, 230, 255), g_fXs);
    }
}

void drawButtons(HDC dc, int hudY, int panelX, const RECT& panel) {
    roundRect(dc, panel, RGB(10, 14, 26), RGB(42, 62, 100), 6);
    text(dc, panelX, hudY + 8, L"CONTROLS", RGB(100, 150, 210), g_fHd);
    const int cols = 2, margin = 6, bh = 36;
    const int bx0 = panelX + 4, by0 = hudY + 34;
    const int bw = ((panel.right - panel.left) - margin * (cols + 1)) / cols;
    bool locked = g_status["motor_lock"].truthy();
    for (size_t i = 0; i < g_buttons.size(); ++i) {
        Button& b = g_buttons[i];
        int col = (int)i % cols, row = (int)i / cols;
        b.rect = {bx0 + col * (bw + margin), by0 + row * (bh + margin), 0, 0};
        b.rect.right = b.rect.left + bw;
        b.rect.bottom = b.rect.top + bh;
        COLORREF base = b.color;
        std::wstring label = b.label;
        if (b.special == Button::Camera) label = L"Cam: " + widen(g_status["active_cam_id"].text("0"));
        if (b.special == Button::Lock) { label = locked ? L"LOCKED" : L"Lock Motors"; base = locked ? RGB(200, 60, 60) : RGB(140, 200, 140); }
        if (b.special == Button::Scheme) label = L"Scheme: " + widen(g_status["drive_scheme"].text("WASD"));
        bool enabled = buttonEnabled(b);
        bool hover = PtInRect(&b.rect, g_mouse);
        COLORREF c = !enabled ? shade(base, -60) : (hover && g_mouseDown) ? shade(base, -30) : hover ? shade(base, 30) : base;
        roundRect(dc, b.rect, c, RGB(80, 80, 80), 12, 2);
        textCentered(dc, b.rect, label, enabled ? RGB(0, 0, 0) : RGB(120, 120, 120), g_fBtn);
    }
}

// MIND panel — the inner life, from /mind (hidden if the robot has none):
// mood + who's there, her four needs, her latest thought, and the last
// exchange, since whoever typed may not hear her answer.
void drawWrapped(HDC dc, RECT& r, const std::wstring& s, COLORREF c, int maxLines) {
    if (s.empty() || r.top >= r.bottom) return;
    HGDIOBJ old = SelectObject(dc, g_fXs);
    SetTextColor(dc, c);
    RECT box{r.left, r.top, r.right, std::min(r.bottom, (LONG)(r.top + 16 * maxLines))};
    DrawTextW(dc, s.c_str(), (int)s.size(), &box, DT_WORDBREAK | DT_END_ELLIPSIS | DT_NOPREFIX | DT_EDITCONTROL);
    RECT calc{r.left, r.top, r.right, r.top};
    DrawTextW(dc, s.c_str(), (int)s.size(), &calc, DT_WORDBREAK | DT_CALCRECT | DT_NOPREFIX | DT_EDITCONTROL);
    SelectObject(dc, old);
    r.top += std::min((LONG)(16 * maxLines), calc.bottom - calc.top) + 4;
}

void drawMind(HDC dc, const RECT& panel) {
    const JValue& m = g_mind;
    if (m.isNull() || m["mood"].isNull() || panel.right - panel.left < 260 || panel.bottom - panel.top < 60) return;
    roundRect(dc, panel, RGB(12, 10, 24), RGB(70, 52, 110), 6);
    int x = panel.left + 10, y = panel.top + 8, w = panel.right - panel.left - 20;
    std::wstring label = widen(m["mood"]["label"].text("?")) + (m["sleeping"].truthy() ? L"  (asleep)" : L"");
    int hw = text(dc, x, y, L"MIND  " + label, RGB(205, 170, 240), g_fSm);
    if (!m["person"].isNull()) text(dc, x + hw + 14, y + 3, L"with " + widen(m["person"].text("")), RGB(120, 230, 170), g_fXs);
    y += 24;
    const char* keys[4] = {"social", "curiosity", "security", "sleepiness"};
    const wchar_t* names[4] = {L"Lonely", L"Curious", L"Jumpy", L"Sleepy"};
    int barW = std::max(60, (w - 4 * 64) / 4);
    for (int i = 0; i < 4; ++i) {
        int bx = x + i * (barW + 64);
        text(dc, bx, y, names[i], RGB(150, 140, 185), g_fXs);
        RECT track{bx + 58, y + 4, bx + 58 + barW, y + 12};
        roundRect(dc, track, RGB(30, 28, 50), RGB(30, 28, 50), 3);
        double v = std::max(0.0, std::min(1.0, m["drives"][keys[i]].num()));
        if (v > 0) { RECT fill = track; fill.right = fill.left + (int)(barW * v); roundRect(dc, fill, RGB(150, 120, 240), RGB(150, 120, 240), 3); }
    }
    y += 22;
    RECT r{x, y, x + w, panel.bottom - 6};
    if (!m["thought"].isNull()) drawWrapped(dc, r, L"... " + widen(m["thought"].text("")), RGB(190, 180, 220), 2);
    const JValue& ex = m["last_exchange"];
    if (!ex.isNull()) {
        drawWrapped(dc, r, L"You: " + widen(ex["you"].text("")), RGB(140, 170, 220), 2);
        drawWrapped(dc, r, L"KIDA: " + widen(ex["kida"].text("")), RGB(230, 190, 240), 3);
    }
}

void drawPrompt(HDC dc, const RECT& client) {
    dim(dc, client, 200);
    RECT box{0, 0, 420, 160};
    OffsetRect(&box, (client.right - 420) / 2, (client.bottom - 160) / 2);
    bool unlock = g_prompt == Prompt::Unlock, chat = g_prompt == Prompt::Chat;
    roundRect(dc, box, RGB(20, 24, 36), unlock ? RGB(200, 80, 80) : chat ? RGB(160, 120, 230) : RGB(80, 140, 220), 10, 2);
    std::wstring title = unlock ? L"ENTER PASSWORD TO UNLOCK MOTORS"
                       : chat ? L"TYPE A MESSAGE TO KIDA" : L"ROBOT ADDRESS (e.g. 192.168.1.50)";
    RECT t = box; t.bottom = t.top + 44;
    textCentered(dc, t, title, RGB(220, 220, 235), g_fSm);
    RECT field{box.left + 20, box.top + 52, box.right - 20, box.top + 86};
    roundRect(dc, field, RGB(10, 12, 20), RGB(70, 80, 110), 4);
    std::wstring shown = unlock ? std::wstring(g_promptText.size(), L'*') : g_promptText;
    if (shown.size() > 44) shown = L"..." + shown.substr(shown.size() - 41);   // keep the end in view
    text(dc, field.left + 8, field.top + 7, shown + L"_", RGB(235, 235, 245), g_fSm);
    RECT hint{box.left, box.top + 94, box.right, box.top + 120};
    std::wstring h = g_unlockPending ? L"checking..." : unlock ? L"Enter = unlock    Esc = cancel"
                   : chat ? L"Enter = send    Esc = cancel" : L"Enter = connect    Esc = quit";
    textCentered(dc, hint, h, RGB(120, 130, 160), g_fXs);
    if (!g_promptError.empty()) {
        RECT e{box.left, box.top + 120, box.right, box.bottom - 6};
        textCentered(dc, e, g_promptError, RGB(255, 100, 100), g_fXs);
    }
}

void paint(HDC dc, const RECT& client) {
    const int sw = client.right, sh = client.bottom;
    fillRect(dc, client, RGB(7, 9, 16));
    SetBkMode(dc, TRANSPARENT);

    // hud_layout.compute_layout
    const int camTop = CAM_PAD, camH = (int)(sh * CAM_H_FRAC);
    const int faceW = std::max(10, (sw - CAM_PAD * 5) / 4), camW = faceW;
    RECT face{CAM_PAD, camTop, CAM_PAD + faceW, camTop + camH};
    RECT cam1{CAM_PAD * 2 + faceW, camTop, CAM_PAD * 2 + faceW + camW, camTop + camH};
    RECT cam0{CAM_PAD * 3 + faceW + camW, camTop, CAM_PAD * 3 + faceW + camW * 2, camTop + camH};
    RECT photo{CAM_PAD * 4 + faceW + camW * 2, camTop, CAM_PAD * 4 + faceW + camW * 3, camTop + camH};
    const int hudY = camTop + camH + CAM_PAD;
    const int senX1 = SEN_X1_OFFSET, senX2 = senX1 + SEN_X2_OFFSET, senTop = hudY + SEN_TOP_OFFSET;
    const int btnX = sw - BTN_PANEL_WIDTH;
    RECT btnPanel{btnX - 6, hudY + 2, sw - 2, sh - 2};

    ImagePtr fFace, fCam1, fCam0, fPhoto;
    if (g_robot) { fFace = g_robot->face(); fCam1 = g_robot->frame(1); fCam0 = g_robot->frame(0); fPhoto = g_robot->lastPhoto(); }
    drawPanel(dc, face, fFace, L"KIDA");
    drawPanel(dc, cam1, fCam1, L"Cam 1");
    drawPanel(dc, cam0, fCam0, L"Cam 0");
    drawPanel(dc, photo, fPhoto, L"Last Photo Taken");

    RECT hud{0, hudY, sw, sh};
    fillRect(dc, hud, RGB(7, 11, 20));
    frameRect(dc, hud, RGB(32, 52, 88), 1);
    drawStatus(dc, hudY, senX1);
    drawSensors(dc, senX1, senX2, senTop);
    drawButtons(dc, hudY, btnX, btnPanel);
    RECT mindPanel{senX2 + 260, hudY + SEN_TOP_OFFSET - 2, btnX - 18, sh - 8};
    drawMind(dc, mindPanel);

    if (g_status["mode"].text("") == "IDLE") {
        dim(dc, client, 220);
        textCentered(dc, client, L"[ IDLE — press 1-8 to select a mode ]", RGB(140, 60, 60), g_fHd);
    }
    if (g_robot && !g_robot->connected()) {
        RECT top{0, 8, sw, 40};
        textCentered(dc, top, L"[ NO CONNECTION TO ROBOT ]", RGB(255, 90, 90), g_fHd);
    }
    if (g_prompt != Prompt::None) drawPrompt(dc, client);
}

// ── the tick: status, gamepad, key heartbeat, redraw ────────────────────
void tick() {
    if (g_robot) {
        g_status = g_robot->status();
        g_mind = g_robot->mind();
        if (g_prompt == Prompt::None || g_prompt == Prompt::Unlock) g_pad.poll(*g_robot, g_status);
        if (!g_keys.empty() && GetTickCount() - g_lastKeyBeat >= KEY_HEARTBEAT_MS) sendKeyDrive();
    }
    InvalidateRect(g_hwnd, nullptr, FALSE);
}

LRESULT CALLBACK WndProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    switch (msg) {
        case WM_CREATE:
            SetTimer(hwnd, TICK_TIMER, TICK_MS, nullptr);
            return 0;
        case WM_TIMER:
            if (wp == TICK_TIMER) tick();
            return 0;
        case WM_ERASEBKGND:
            return 1;
        case WM_PAINT: {
            PAINTSTRUCT ps;
            HDC dc = BeginPaint(hwnd, &ps);
            RECT client;
            GetClientRect(hwnd, &client);
            HDC mem = CreateCompatibleDC(dc);
            HBITMAP bmp = CreateCompatibleBitmap(dc, std::max(1L, client.right), std::max(1L, client.bottom));
            HGDIOBJ old = SelectObject(mem, bmp);
            paint(mem, client);
            BitBlt(dc, 0, 0, client.right, client.bottom, mem, 0, 0, SRCCOPY);
            SelectObject(mem, old);
            DeleteObject(bmp);
            DeleteDC(mem);
            EndPaint(hwnd, &ps);
            return 0;
        }
        case WM_KEYDOWN:
        case WM_SYSKEYDOWN:
            if (!(lp & (1 << 30))) onKeyDown((int)wp);   // ignore auto-repeat
            return 0;
        case WM_KEYUP:
        case WM_SYSKEYUP:
            onKeyUp((int)wp);
            return 0;
        case WM_CHAR:
            if (g_swallowChar) { g_swallowChar = false; return 0; }
            if (g_prompt != Prompt::None && wp >= 32 && wp != 127
                && g_promptText.size() < (g_prompt == Prompt::Chat ? 500u : 64u)) {
                g_promptText.push_back((wchar_t)wp);
                g_promptError.clear();
            }
            return 0;
        case WM_KILLFOCUS:
            releaseAllDriveKeys();          // alt-tabbed away mid-drive: stop
            return 0;
        case WM_MOUSEMOVE:
            g_mouse = {GET_X_LPARAM(lp), GET_Y_LPARAM(lp)};
            return 0;
        case WM_LBUTTONDOWN:
            g_mouseDown = true;
            SetCapture(hwnd);
            return 0;
        case WM_LBUTTONUP: {
            g_mouseDown = false;
            ReleaseCapture();
            POINT p{GET_X_LPARAM(lp), GET_Y_LPARAM(lp)};
            if (g_prompt == Prompt::None)
                for (const auto& b : g_buttons) if (PtInRect(&b.rect, p)) { clickButton(b); break; }
            return 0;
        }
        case WM_UNLOCK_RESULT:
            g_unlockPending = false;
            if (wp) { g_prompt = Prompt::None; g_promptText.clear(); }
            else { g_promptError = L"Wrong password — motors stay locked"; g_promptText.clear(); }
            return 0;
        case WM_CLOSE:
            DestroyWindow(hwnd);
            return 0;
        case WM_DESTROY:
            KillTimer(hwnd, TICK_TIMER);
            if (g_robot) {
                releaseAllDriveKeys();       // never leave her driving
                g_pad.shutdown(*g_robot);
                g_robot->stop();             // flushes the queued stops first
            }
            PostQuitMessage(0);
            return 0;
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

HFONT makeFont(int px, const wchar_t* face, int weight = FW_NORMAL) {
    return CreateFontW(-px, 0, 0, 0, weight, FALSE, FALSE, FALSE, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS,
                       CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, FIXED_PITCH | FF_MODERN, face);
}

std::string startupAddress() {
    int argc = 0;
    LPWSTR* argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    std::string addr;
    int port = 0;
    for (int i = 1; argv && i < argc; ++i) {
        std::wstring a = argv[i];
        if (a == L"--port" && i + 1 < argc) port = _wtoi(argv[++i]);
        else if (addr.empty()) addr = narrow(a);
    }
    if (argv) LocalFree(argv);
    if (!addr.empty() && port > 0 && addr.find(':') == std::string::npos) addr += ":" + std::to_string(port);
    if (addr.empty()) {
        char env[512];
        DWORD n = GetEnvironmentVariableA("ROBOT_URL", env, sizeof env);
        if (n > 0 && n < sizeof env) addr = env;
    }
    if (addr.empty()) addr = savedAddress();
    return addr;
}

}  // namespace

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE, PWSTR, int show) {
    CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    SetProcessDPIAware();

    g_fSm = makeFont(16, L"Consolas");
    g_fXs = makeFont(13, L"Consolas");
    g_fHd = makeFont(21, L"Consolas", FW_BOLD);
    g_fNoSig = makeFont(15, L"Consolas");
    g_fBtn = CreateFontW(-15, 0, 0, 0, FW_SEMIBOLD, FALSE, FALSE, FALSE, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS,
                         CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_SWISS, L"Segoe UI");
    createButtons();

    WNDCLASSEXW wc{sizeof wc};
    wc.style = CS_HREDRAW | CS_VREDRAW;
    wc.lpfnWndProc = WndProc;
    wc.hInstance = inst;
    wc.hCursor = LoadCursor(nullptr, IDC_ARROW);
    wc.hIcon = LoadIcon(inst, MAKEINTRESOURCE(1));
    wc.lpszClassName = L"KidaController";
    RegisterClassExW(&wc);

    g_hwnd = CreateWindowExW(0, wc.lpszClassName, L"KIDA — Remote Controller", WS_OVERLAPPEDWINDOW,
                             CW_USEDEFAULT, CW_USEDEFAULT, 1600, 900, nullptr, nullptr, inst, nullptr);
    g_pad.onUnlockRequest = openUnlock;

    std::string addr = startupAddress();
    if (addr.empty() || !connectTo(addr)) {
        g_prompt = Prompt::Address;
        g_promptText = widen(addr);
    }

    ShowWindow(g_hwnd, show == SW_SHOWDEFAULT || show == SW_SHOWNORMAL ? SW_MAXIMIZE : show);
    UpdateWindow(g_hwnd);

    MSG m;
    while (GetMessageW(&m, nullptr, 0, 0) > 0) {
        TranslateMessage(&m);
        DispatchMessageW(&m);
    }
    CoUninitialize();
    return 0;
}
