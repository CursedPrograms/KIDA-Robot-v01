@echo off
rem build.bat — build KIDA-Controller.exe with MinGW-w64 g++ (e.g. WinLibs: winget install BrechtSanders.WinLibs.POSIX.UCRT)
rem Output: controller\cpp\build\KIDA-Controller.exe — a single, statically linked exe (no DLLs to ship).
setlocal
cd /d "%~dp0"
if not exist build mkdir build
windres src\app.rc -O coff -o build\app.res || goto :fail
g++ -std=c++17 -O2 -s -municode -mwindows -static ^
    src\main.cpp build\app.res -o build\KIDA-Controller.exe ^
    -lwinhttp -lwindowscodecs -lole32 -lxinput1_4 -lwinmm -lmsimg32 -lgdi32 -luser32 -lshell32 || goto :fail
echo Built build\KIDA-Controller.exe
exit /b 0
:fail
echo Build failed.
exit /b 1
