@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo The local environment is not ready. Double-click setup.bat first.
    pause
    exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" desktop_app.py
