@echo off
REM Sign in ONCE to the kids' YouTube channel (opens the browser: choose the kids' channel).
setlocal
set SCRIPT_DIR=%~dp0
set PYTHONIOENCODING=utf-8
set "PYTHONPATH=%SCRIPT_DIR%;%PYTHONPATH%"
cd /d "%SCRIPT_DIR%"
"%SCRIPT_DIR%.venv\Scripts\python.exe" -m stories signin --series kids
pause
