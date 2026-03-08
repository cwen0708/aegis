@echo off
title Aegis Dev

echo Starting Aegis Backend...
start "Aegis Backend" cmd /k "cd /d %~dp0backend && venv\Scripts\activate && python dev.py"

echo Starting Aegis Frontend...
start "Aegis Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

echo.
echo Aegis dev servers launched in separate windows.
echo   Backend:  http://localhost:8899
echo   Frontend: http://localhost:5173
