@echo off
rem Drag a Short's folder onto this file (or double-click and paste the path).
rem Renders the final video in 8K on this PC (uses the NVIDIA GPU when available)
rem and makes the thumbnail. The Short must already have a short.json.
setlocal
cd /d "%~dp0"
set "PY=python"
where python >nul 2>nul || set "PY=py -3"
set "TARGET=%~1"
if "%TARGET%"=="" set /p "TARGET=Drag the Short's folder here and press Enter: "
set "TARGET=%TARGET:"=%"
%PY% sm.py render "%TARGET%" --res 8k
if errorlevel 1 goto end
%PY% sm.py thumb "%TARGET%"
:end
echo.
pause
