@echo off
title Aegis

echo Building frontend...
cd /d "%~dp0frontend"
echo y | call npm run build

echo Starting Aegis Backend...
start "Aegis Backend" /min cmd /c "cd /d %~dp0backend && venv\Scripts\activate.bat && python -m uvicorn app.main:app --host 127.0.0.1 --port 8899"

echo Starting Aegis Frontend...
start "Aegis Frontend" /min cmd /c "cd /d %~dp0frontend && npx serve dist -l 5173 -s"

timeout /t 3 >nul
echo.
echo Aegis is running!
echo   Open: http://localhost:5173
start http://localhost:5173
