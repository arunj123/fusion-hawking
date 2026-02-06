@echo off
setlocal

REM Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Python not found. Please install Python 3.8+
    exit /b 1
)

REM Create Venv if missing
if not exist ".venv" (
    echo Creating Python Virtual Environment...
    python -m venv .venv
)

REM Activate Venv
REM Activate Venv
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else (
    echo Warning: Venv Scripts not found. Recreating venv...
    rmdir /s /q .venv
    python -m venv .venv
    call .venv\Scripts\activate.bat
)

REM Check Requests
pip show pytest >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing dependencies...
    pip install -r requirements.txt
)

REM Run Fusion
echo Starting Fusion Automation...
python -m tools.fusion.main %*

if %errorlevel% neq 0 (
    echo Fusion Failed.
    exit /b 1
)
