@echo off
REM options.bat - the options menu for this bot (options.py edits config.json).
REM Uses the bot's own venv when there is one, and installs pygame into it if missing.
setlocal
cd /d "%~dp0"
set "PY="
for %%v in (venv venv311 .venv scripts\.venv) do if not defined PY if exist "%%v\Scripts\python.exe" set "PY=%%v\Scripts\python.exe"
if not defined PY set "PY=py -3"
%PY% -c "import pygame" 2>nul || %PY% -m pip install pygame
%PY% options.py %*
if errorlevel 1 pause
