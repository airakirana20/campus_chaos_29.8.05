@echo off
setlocal

cd /d "%~dp0"

set "PYTHON_BIN=py"

where %PYTHON_BIN% >nul 2>nul
if errorlevel 1 (
    set "PYTHON_BIN=python"
    where %PYTHON_BIN% >nul 2>nul
    if errorlevel 1 (
        echo python is not installed on this Windows machine yet.
        pause
        exit /b 1
    )
)

if not exist ".venv" (
    %PYTHON_BIN% -m venv .venv
    if errorlevel 1 (
        echo Failed to create .venv
        pause
        exit /b 1
    )
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo Failed to activate .venv
    pause
    exit /b 1
)

python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install requirements
    pause
    exit /b 1
)

python main.py
if errorlevel 1 (
    echo Game exited with an error
    pause
    exit /b 1
)

endlocal
