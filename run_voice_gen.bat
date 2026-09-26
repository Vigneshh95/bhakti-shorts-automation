@echo off
echo.
echo Select a voice for Murugan:
echo.
echo 1. Baby
echo 2. Young Male
echo 3. Male
echo.

set /p choice="Enter your choice (1, 2, or 3): "

if "%choice%"=="1" (
    set voice_style=baby
) else if "%choice%"=="2" (
    set voice_style=young_male
) else if "%choice%"=="3" (
    set voice_style=male
) else (
    echo Invalid choice. Exiting.
    exit /b
)

echo.
echo Starting voice generation with %voice_style% voice...
echo.

python murugan_voice_gen.py --voice %voice_style%

echo.
echo Voice generation complete.
echo.
echo Starting video generation...
echo.

python create_video.py --character %voice_style%

echo.
echo Video generation complete.
pause