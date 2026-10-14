@echo off
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
    echo Run setup.ps1 first to install Python dependencies.
    pause
    exit /b 1
)
start "" /D "%~dp0" "%~dp0.venv\Scripts\pythonw.exe" -X utf8 "%~dp0gui_launcher.py"
