@echo off
REM Pause or resume a cloud pipeline (for example if something is wrong in the videos).
REM A paused pipeline still starts on its schedule, but stops at once without making or uploading anything.
setlocal
set SCRIPT_DIR=%~dp0
set PYTHONIOENCODING=utf-8
set "PYTHONPATH=%SCRIPT_DIR%;%PYTHONPATH%"
cd /d "%SCRIPT_DIR%"
set PY="%SCRIPT_DIR%.venv\Scripts\python.exe"
%PY% -m autopilot pauses
echo.
echo   1  Short - Murugan          5  Story - Grown-ups
echo   2  Short - Mahaperiyava     6  Story - Kids
echo   3  Short - Kids Krishna     7  ALL pipelines
echo   4  Short - Kids Murugan
echo.
set /p N=Which pipeline (1-7)? 
set NAME=
if "%N%"=="1" set NAME=short-murugan
if "%N%"=="2" set NAME=short-periyava
if "%N%"=="3" set NAME=short-krishna
if "%N%"=="4" set NAME=short-kids
if "%N%"=="5" set NAME=story-adults
if "%N%"=="6" set NAME=story-kids
if "%N%"=="7" set NAME=all
if "%NAME%"=="" (echo Nothing changed. & pause & exit /b 1)
set /p A=Type P to PAUSE it or R to RESUME it: 
if /i "%A%"=="P" (%PY% -m autopilot pause %NAME%) else if /i "%A%"=="R" (%PY% -m autopilot resume %NAME%) else (echo Nothing changed.)
echo.
%PY% -m autopilot pauses
pause
