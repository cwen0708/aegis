@echo off
title Aegis

echo Building frontend...
cd /d "%~dp0frontend"
echo y | call npm run build

echo Starting Aegis...
start "Aegis" /min cmd /c "cd /d %~dp0backend && venv\Scripts\activate.bat && python -m uvicorn app.main:app --host 127.0.0.1 --port 8899"

timeout /t 3 >nul
echo.
echo Aegis is running!
echo   Open: http://localhost:8899
start http://localhost:8899
