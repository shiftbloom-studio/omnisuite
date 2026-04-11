@echo off
setlocal

set "PYTHON_BIN="
if exist ".venv\Scripts\python.exe" set "PYTHON_BIN=.venv\Scripts\python.exe"
if not defined PYTHON_BIN py -3.13 -c "import sys" >nul 2>&1 && set "PYTHON_BIN=py -3.13"
if not defined PYTHON_BIN py -3.12 -c "import sys" >nul 2>&1 && set "PYTHON_BIN=py -3.12"
if not defined PYTHON_BIN py -3.11 -c "import sys" >nul 2>&1 && set "PYTHON_BIN=py -3.11"
if not defined PYTHON_BIN set "PYTHON_BIN=python"

set "PYTORCH_ENABLE_MPS_FALLBACK=1"

echo ========================================
echo   OmniSuite - Voice Synthesis ^& Cloning
echo ========================================
echo.
echo Using Python: %PYTHON_BIN%
echo Starting server at http://localhost:8000
echo Press Ctrl+C to stop.
echo.
%PYTHON_BIN% -m uvicorn app:app --host 127.0.0.1 --port 8000 --reload
pause
