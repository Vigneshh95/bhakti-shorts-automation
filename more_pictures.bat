@echo off
REM Paints about 20 new baby-Murugan pictures free on your Kaggle GPU (about 2 hours;
REM the laptop can be used meanwhile). More: more_pictures.bat --count 40.
REM They land in daily_images\new_pictures\ -- move the ones you like into daily_images\.
setlocal
set SCRIPT_DIR=%~dp0
set PYTHONIOENCODING=utf-8
set "PYTHONPATH=%SCRIPT_DIR%;%PYTHONPATH%"
cd /d "%SCRIPT_DIR%"
"%SCRIPT_DIR%.venv\Scripts\python.exe" -m autopilot pictures %*
pause
