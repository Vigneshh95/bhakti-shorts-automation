@echo off
REM One click: today's Ramana Maharshi Short (Deivathin Kural essence) - chapter, script,
REM voice + talking face on Kaggle, video, and scheduled upload (06:30 IST). About 20-25 min.
REM   ramana_short.bat               normal run
REM   ramana_short.bat --no-upload   everything except the upload
setlocal
set SCRIPT_DIR=%~dp0
set PYTHONIOENCODING=utf-8
set "PYTHONPATH=%SCRIPT_DIR%;%PYTHONPATH%"
cd /d "%SCRIPT_DIR%"
"%SCRIPT_DIR%.venv\Scripts\python.exe" -m autopilot --series ramana run %*
set CODE=%ERRORLEVEL%
echo %* | find /i "--scheduled" >nul
if errorlevel 1 (
    if not "%CODE%"=="0" (
        echo.
        echo Failed - see the message above. Full log: episodes\ramana\^<today^>\run.log
    )
    pause
)
exit /b %CODE%
