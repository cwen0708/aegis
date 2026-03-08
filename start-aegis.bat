@echo off
chcp 65001 >nul 2>&1
title Aegis
echo.
echo  Starting Aegis...
echo.

set "PROJECT_DIR=%~dp0"

:: Build frontend (served by backend as static files)
echo  [1/2] Building frontend...
cd /d "%PROJECT_DIR%frontend"
call npm run build
if %ERRORLEVEL% NEQ 0 (
    if exist "%PROJECT_DIR%frontend\dist\index.html" (
        echo  [!] Frontend build failed, using existing build
    ) else (
        echo  [X] Frontend build failed and no existing build found
        echo  [!] Please run: cd frontend ^&^& npm install ^&^& npm run build
        pause
        exit /b 1
    )
) else (
    echo  [OK] Frontend built
)

:: Start server (backend serves both API and frontend)
echo  [2/2] Starting server...
cd /d "%PROJECT_DIR%backend"
start "Aegis Server" /min cmd /c "call venv\Scripts\activate.bat && python -m uvicorn app.main:app --host 127.0.0.1 --port 8899"

:: Wait for server to be ready
echo  Waiting for server...
:wait_server
timeout /t 2 /nobreak >nul
curl -sf http://127.0.0.1:8899/health >nul 2>&1
if %ERRORLEVEL% NEQ 0 goto wait_server
echo  [OK] Server is ready

:: Open browser
start http://localhost:8899

echo.
echo  ╔══════════════════════════════════════╗
echo  ║  Aegis is running!                   ║
echo  ║                                      ║
echo  ║  http://localhost:8899               ║
echo  ║                                      ║
echo  ║  Close this window to stop Aegis.    ║
echo  ╚══════════════════════════════════════╝
echo.
echo  Press any key to stop all services...
pause >nul

:: Kill background processes
taskkill /fi "WINDOWTITLE eq Aegis Server" /f >nul 2>&1
echo  Aegis stopped.
