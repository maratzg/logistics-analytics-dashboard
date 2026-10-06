@echo off
setlocal EnableExtensions

cd /d "%~dp0"

if not exist requirements.txt (
    echo requirements.txt was not found in this folder.
    echo Make sure this batch file is inside the history_dashboard project folder.
    pause
    exit /b 1
)

set "PYTHON_LAUNCHER="
set "PYTHON_ARGS="

where py >nul 2>nul
if not errorlevel 1 (
    py -3.13 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 13) else 1)" >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_LAUNCHER=py"
        set "PYTHON_ARGS=-3.13"
    )
)

if not defined PYTHON_LAUNCHER (
    where python >nul 2>nul
    if not errorlevel 1 (
        python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 13) else 1)" >nul 2>nul
        if not errorlevel 1 set "PYTHON_LAUNCHER=python"
    )
)

if not defined PYTHON_LAUNCHER (
    echo Python 3.13 was not found.
    echo Install it with company IT approval, then run this setup again.
    echo Suggested command: winget install Python.Python.3.13
    echo.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating the project-local Python environment...
    %PYTHON_LAUNCHER% %PYTHON_ARGS% -m venv .venv
    if errorlevel 1 goto :failed
)

echo Installing requirements into .venv...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :failed

echo Running the environment check...
".venv\Scripts\python.exe" check_environment.py
if errorlevel 1 goto :failed

echo.
echo History Dashboard setup completed successfully.
echo Normal use: double-click launch_history_dashboard.vbs
echo The setup does not need to be rerun for each launch.
pause
exit /b 0

:failed
echo.
echo Setup did not complete. Review the message above or ask IT for help.
pause
exit /b 1
