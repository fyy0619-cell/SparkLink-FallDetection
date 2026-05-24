@echo off
title Fall Alert Backend (PushPlus)
rem ================================================================
rem Double-click to launch the PushPlus backend.
rem fall_alert_backend_demo.py auto-loads fall_alert_backend.env
rem from its own directory, so this .bat just chdir + run.
rem Stop with Ctrl+C or close the window.
rem ================================================================

cd /d "%~dp0"

echo.
echo ================================================================
echo  Fall Alert Backend - PushPlus
echo ================================================================
echo  Working dir: %CD%
echo.

if not exist "fall_alert_backend.env" (
    echo [ERROR] fall_alert_backend.env not found.
    echo [ERROR] Copy fall_alert_backend.env.example, fill PUSHPLUS_TOKEN, retry.
    pause
    exit /b 1
)

set PYTHONUNBUFFERED=1
python fall_alert_backend_demo.py

echo.
echo ----------------------------------------------------------------
echo Backend exited. Press any key to close.
pause >nul
