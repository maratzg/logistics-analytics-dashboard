@echo off
setlocal

cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "%CD%\main.py"
    exit /b 0
)

echo The project-local Python environment was not found.
echo Run install_dependencies.bat once, then launch the dashboard again.
echo.
pause
exit /b 1
