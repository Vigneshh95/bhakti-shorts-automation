@echo off
REM One click: write today's Murugan Short, make the image and video, and schedule it on YouTube.
REM   auto_short.bat               normal run (uploads, goes public at publish_time in autopilot.toml)
REM   auto_short.bat --no-upload   preview: everything except the upload
REM The daily Windows task runs this with --scheduled.
setlocal
set SCRIPT_DIR=%~dp0
set PYTHONIOENCODING=utf-8
set "PYTHONPATH=%SCRIPT_DIR%;%PYTHONPATH%"
cd /d "%SCRIPT_DIR%"
"%SCRIPT_DIR%.venv\Scripts\python.exe" -m autopilot run %*
set CODE=%ERRORLEVEL%
echo %* | find /i "--scheduled" >nul
if errorlevel 1 (
    if not "%CODE%"=="0" (
        echo.
        echo Failed - see the message above. Full log: episodes\auto\^<today^>\run.log
    )
    pause
)
exit /b %CODE%
