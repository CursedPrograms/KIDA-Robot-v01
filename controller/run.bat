@echo off
rem run.bat - launch the KIDA-01 remote controller (creates its own venv on first run): calls run.ps1
rem Usage: run.bat <robot-ip-or-url> [--port 5004] [--emulate]
rem        run.bat          no robot: EMULATE, her pretend self on this PC
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
if errorlevel 1 pause
