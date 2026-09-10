@echo off
REM =======================================================
REM DeskPilot Build Script for Windows CMD
REM =======================================================

echo.
echo =======================================================
echo        DeskPilot Windows Build Pipeline (v2.0.0)       
echo =======================================================
echo.

cd /d "%~dp0.."

echo [1/3] Verifying PyInstaller...
python -m pip install pyinstaller

echo.
echo [2/3] Building executable with PyInstaller...
python -m PyInstaller deskpilot.spec --noconfirm

if not exist "dist\DeskPilot\DeskPilot.exe" (
    echo [ERROR] Build failed. dist\DeskPilot\DeskPilot.exe not found.
    exit /b 1
)

echo.
echo [3/3] Standalone application built successfully!
echo Executable: %cd%\dist\DeskPilot\DeskPilot.exe
echo.

where iscc >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo Compiling Inno Setup installer...
    iscc installer\deskpilot_setup.iss
    echo Installer built in dist\installer\
) else (
    echo Note: Inno Setup (iscc) not found in PATH.
    echo Standalone executable is ready at dist\DeskPilot\DeskPilot.exe
    echo To build the setup installer, install Inno Setup 6 and run:
    echo iscc installer\deskpilot_setup.iss
)

echo.
echo Build complete.
pause
