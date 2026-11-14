@echo off
rem One-time check for this PC: Python packages, ffmpeg and GPU encoder.
setlocal
cd /d "%~dp0"
set "PY=python"
where python >nul 2>nul || set "PY=py -3"
%PY% --version || (echo Python not found. Install: winget install Python.Python.3.12 & goto end)
%PY% -m pip install --quiet pillow numpy
where ffmpeg >nul 2>nul || echo ffmpeg not found. Install: winget install Gyan.FFmpeg   (then close this window and run this again)
%PY% sm.py doctor
:end
echo.
pause
