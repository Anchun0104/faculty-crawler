@echo off
setlocal
cd /d "%~dp0"

echo Checking Python 3.11 or newer...
set "PYTHON_CMD="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD goto :python_missing

%PYTHON_CMD% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 goto :python_missing
%PYTHON_CMD% -c "import tkinter; root = tkinter.Tk(); root.withdraw(); root.destroy()"
if errorlevel 1 goto :tkinter_missing

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys" >nul 2>nul
    if errorlevel 1 (
        echo Removing an unusable local virtual environment...
        rmdir /s /q ".venv"
        if errorlevel 1 goto :failed
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating the local virtual environment...
    %PYTHON_CMD% -m venv .venv
    if errorlevel 1 goto :failed
)

echo Installing Python packages...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :failed

echo Installing Playwright Chromium...
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 goto :failed

echo.
echo Setup completed. You can now double-click start.bat.
pause
exit /b 0

:python_missing
echo.
echo Python 3.11 or newer was not found.
echo Install Python from https://www.python.org/downloads/windows/ and enable the Python launcher.
pause
exit /b 1

:tkinter_missing
echo.
echo This Python installation does not include tkinter.
echo Reinstall Python from python.org and include Tcl/Tk support.
pause
exit /b 1

:failed
echo.
echo Setup failed. Check the messages above and try again.
pause
exit /b 1
