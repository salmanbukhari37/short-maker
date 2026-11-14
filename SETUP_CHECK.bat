@echo off
rem One-time check for this PC: Python packages, ffmpeg and GPU encoder.
setlocal
cd /d "%~dp0"
set "PY=python"
where python >nul 2>nul || set "PY=py -3"
%PY% --version || (echo Python nahi mila. Install: winget install Python.Python.3.12 & goto end)
%PY% -m pip install --quiet pillow numpy
where ffmpeg >nul 2>nul || echo ffmpeg nahi mila. Install: winget install Gyan.FFmpeg   (phir yeh window band karke dobara chalayen)
%PY% sm.py doctor
:end
echo.
pause
