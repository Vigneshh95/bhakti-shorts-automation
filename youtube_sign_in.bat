@echo off
REM A fresh YouTube sign-in (opens the browser; approve with the channel's Google account).
REM Do this once after switching the Google Cloud app to "In production", then paste the new
REM murugan_token.json into the YT_TOKEN_JSON secret on GitHub so the cloud runs can upload.
setlocal
set SCRIPT_DIR=%~dp0
set PYTHONIOENCODING=utf-8
set "PYTHONPATH=%SCRIPT_DIR%;%PYTHONPATH%"
cd /d "%SCRIPT_DIR%"
"%SCRIPT_DIR%.venv\Scripts\python.exe" -m autopilot signin
pause
