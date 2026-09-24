# KIDA Remote Controller — native Windows (.exe)

The C++ version of `controller/main.py`: same HUD, same keys, same gamepad layout,
talking to the robot's Flask server. One statically linked `.exe`, no Python and no
DLLs to ship (only what comes with Windows 10/11).

## Build

Needs MinGW-w64 g++ (e.g. `winget install BrechtSanders.WinLibs.POSIX.UCRT`), then:

```bat
controller\cpp\build.bat
```

→ `controller\cpp\build\KIDA-Controller.exe`. (Or `cmake -S . -B build -G "MinGW Makefiles" && cmake --build build`.)

## Run

```bat
KIDA-Controller.exe 192.168.1.50            :: port 5004
KIDA-Controller.exe http://192.168.1.50:5004
```

Or set `ROBOT_URL`, or just double-click it: it asks for the address once and
remembers it in `kida_controller.ini` next to the exe.

## Controls

| Keyboard (KEYBOARD mode) | |
|---|---|
| WASD scheme | W/S drive, A/D rotate, **W+A / W+D / S+A / S+D curve while driving** |
| QAWS (tank) scheme | Q/A left track, W/S right track |
| `1`–`8` | drive mode |
| Space / X / I / M / L / K | stop / speed / inference / music / LEDs / LED effects |
| U | lock motors, or unlock (password prompt) |
| C / V | photo / video |
| `,` / `.` | WASD / tank scheme |
| Esc (and Q in WASD) | quit |

| Gamepad (XInput — Logitech F710 switch on **X**, Xbox pads) | |
|---|---|
| Left stick | drive (WASD scheme) |
| LT / RT | left / right track, analog; hold LB / RB to reverse (tank scheme) |
| Right stick | aim the sensor servo |
| A / B / X / Y | photo / stop / speed − / speed + |
| D-pad ← / → | previous / next mode (LB / RB too in the WASD scheme) |
| D-pad ↑ (or RT in WASD) | video on/off |
| Start / Back | lock-unlock / LIDAR sweep |
| Rumble | obstacles, tipping, vibration — whatever the robot asks for |

Any other joystick (e.g. the Generic USB Joystick) works through winmm: stick to drive,
first four buttons = photo / stop / speed − / speed +.

Every drive command is resent while held, and letting go, losing focus or closing the
window stops the robot — it also stops by itself if it hears nothing for ~0.8 s.
