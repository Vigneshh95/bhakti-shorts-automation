@echo off
REM After adding or removing pictures in daily_images\ or periyava_images\: sends them to the
REM private cloud copy, so the automatic daily runs (GitHub Actions) use them too.
setlocal
set SCRIPT_DIR=%~dp0
set PYTHONIOENCODING=utf-8
set "PYTHONPATH=%SCRIPT_DIR%;%PYTHONPATH%"
cd /d "%SCRIPT_DIR%"
"%SCRIPT_DIR%.venv\Scripts\python.exe" -m autopilot sync
pause
