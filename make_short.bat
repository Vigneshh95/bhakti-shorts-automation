@echo off
REM Build a Short:   make_short.bat episodes\2026-09-27  [--preset fast|balanced|best] [--voice baby|young_male|male]
setlocal
set SCRIPT_DIR=%~dp0
set PYTHONIOENCODING=utf-8
if "%~1"=="" (
    echo Usage: make_short.bat episodes\^<name^> [--preset fast^|balanced^|best] [--voice baby^|young_male^|male]
    echo Create a new episode first with:  .venv\Scripts\python.exe -m shorts new ^<name^>
    exit /b 2
)
"%SCRIPT_DIR%.venv\Scripts\python.exe" -m shorts make %*
set CODE=%ERRORLEVEL%
if not %CODE%==0 echo. & echo Failed - see the message above.
pause
exit /b %CODE%
