@echo off
REM Saves the sign-in as sign_in_files\2_Kids_channel_YouTube_sign_in.json: paste it into its GitHub secret (see sign_in_files\README.txt).
REM Sign in ONCE to the kids' YouTube channel (opens the browser: choose the kids' channel).
setlocal
set SCRIPT_DIR=%~dp0
set PYTHONIOENCODING=utf-8
set "PYTHONPATH=%SCRIPT_DIR%;%PYTHONPATH%"
cd /d "%SCRIPT_DIR%"
"%SCRIPT_DIR%.venv\Scripts\python.exe" -m stories signin --series kids
echo.
echo Now open sign_in_files\README.txt: it says which GitHub secret this file goes into.
explorer sign_in_files
pause
