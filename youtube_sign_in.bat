@echo off
REM A fresh YouTube sign-in (opens the browser; approve with the channel's Google account).
REM Do this once after switching the Google Cloud app to "In production", then paste the new
REM sign_in_files\1_BrahmaNadagam_YouTube_sign_in.json into the YT_TOKEN_JSON secret on GitHub so the cloud runs can upload.
setlocal
set SCRIPT_DIR=%~dp0
set PYTHONIOENCODING=utf-8
set "PYTHONPATH=%SCRIPT_DIR%;%PYTHONPATH%"
cd /d "%SCRIPT_DIR%"
"%SCRIPT_DIR%.venv\Scripts\python.exe" -m autopilot signin
echo.
echo Now open sign_in_files\README.txt: it says which GitHub secret this file goes into.
explorer sign_in_files
pause
