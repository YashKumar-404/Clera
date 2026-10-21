@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [setup] creating a local Python environment...
    py -3 -m venv .venv 2>nul || python -m venv .venv
    if errorlevel 1 goto :nopython
    echo [setup] installing dependencies...
    ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
    ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
    if errorlevel 1 goto :fail
)

if not exist "assets\avatar.png" (
    echo [setup] drawing the pixel art...
    ".venv\Scripts\python.exe" scripts\make_assets.py
)

echo [run] warming up Pixel Girlfriend...
".venv\Scripts\python.exe" scripts\ai_girlfriend.py
if errorlevel 1 goto :fail
exit /b 0

:nopython
echo.
echo Python 3 was not found. Install it from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH" during setup.
echo.
pause
exit /b 1

:fail
echo.
echo Something went wrong - the message above explains what.
echo If it mentions Ollama, open a terminal and run:  ollama serve
echo.
pause
exit /b 1
