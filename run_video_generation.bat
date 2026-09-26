@echo off
setlocal

REM Get the directory of the batch file
set SCRIPT_DIR=%~dp0

REM Activate the virtual environment if it exists
set VENV_PATH=%SCRIPT_DIR%.venv\Scripts\activate
if exist "%VENV_PATH%" (
    echo Activating virtual environment...
    call "%VENV_PATH%"
) else (
    echo Virtual environment not found, continuing with system Python.
)

:menu
echo.
echo Select a voice for video generation:
echo 1. Baby
echo 2. Young Male
echo 3. Male
echo 4. All
echo 5. Exit
echo.

set /p choice="Enter your choice (1-5): "

if "%choice%"=="1" set voice=baby
if "%choice%"=="2" set voice=young_male
if "%choice%"=="3" set voice=male
if "%choice%"=="4" set voice=all
if "%choice%"=="5" exit /b

if not defined voice (
    echo Invalid choice. Please try again.
    goto menu
)

echo Running video generation for %voice%...
python "%SCRIPT_DIR%test.py" --voice %voice%

echo.
echo Video generation process finished.
pause
