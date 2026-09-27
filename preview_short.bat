@echo off
REM Make today's automatic Short WITHOUT uploading, then open it so you can watch it.
REM If you're happy with it, run auto_short.bat: it reuses this same video and uploads it.
setlocal
set SCRIPT_DIR=%~dp0
set PYTHONIOENCODING=utf-8
set "PYTHONPATH=%SCRIPT_DIR%;%PYTHONPATH%"
cd /d "%SCRIPT_DIR%"
"%SCRIPT_DIR%.venv\Scripts\python.exe" -m autopilot run --no-upload %*
set CODE=%ERRORLEVEL%
if not "%CODE%"=="0" goto :failed
for /f "delims=" %%F in ('dir /b /o-d "%SCRIPT_DIR%Final\auto\muruganAuto_*.mp4" 2^>nul') do (
    echo.
    echo Opening Final\auto\%%F ...
    start "" "%SCRIPT_DIR%Final\auto\%%F"
    goto :opened
)
:opened
echo.
echo Happy with it? Run auto_short.bat to upload this same video to YouTube.
goto :end
:failed
echo.
echo Failed - see the message above.
:end
pause
exit /b %CODE%
