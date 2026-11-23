@echo off
title Smart Traffic ^& Helmet Detection System
cd /d "%~dp0backend"

set PY=python
if exist .venv\Scripts\python.exe set PY=.venv\Scripts\python.exe

echo [1/3] Checking Python dependencies...
%PY% -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo Failed to install Python dependencies.
    pause
    exit /b 1
)

if not exist ..\frontend\dist (
    echo [2/3] Building React UI ^(first run only^)...
    pushd ..\frontend
    call npm install --no-fund --no-audit
    call npm run build
    popd
) else (
    echo [2/3] React UI already built.
)

echo [3/3] Starting server at http://127.0.0.1:8000
echo Press Ctrl+C to stop.
%PY% main.py
pause
