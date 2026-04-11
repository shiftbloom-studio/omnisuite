@echo off
echo ========================================
echo   OmniSuite - Voice Synthesis ^& Cloning
echo ========================================
echo.
echo Starting server at http://localhost:8000
echo Press Ctrl+C to stop.
echo.
python -m uvicorn app:app --host 127.0.0.1 --port 8000 --reload
pause
