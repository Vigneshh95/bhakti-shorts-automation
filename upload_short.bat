@echo off
setlocal

REM Get the directory of the batch file
set SCRIPT_DIR=%~dp0

REM --- Activate Python Virtual Environment ---
set VENV_PATH=%SCRIPT_DIR%.venv\Scripts\activate.bat
if exist "%VENV_PATH%" (
    echo Activating virtual environment...
    call "%VENV_PATH%"
) else (
    echo Warning: Virtual environment not found at %VENV_PATH%.
    echo The script will try to run with the system's Python installation.
    echo If you encounter errors, make sure the required packages are installed.
)

REM --- Run the Upload Script ---
echo.
echo Starting the YouTube upload process...
python "%SCRIPT_DIR%autouploadmurugan.py"

REM --- Finish ---
echo.
echo =================================================
echo Upload script finished.
echo If there were any errors, they will be displayed above.
echo If the upload was successful, you will see a "✅ Upload successful!" message.
echo Press any key to close this window.
echo =================================================
pause
