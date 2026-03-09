@echo off
title Aegis Dev

echo Killing existing processes on ports 8899 and 8888...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8899 ^| findstr LISTENING') do taskkill /PID %%a /F >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8888 ^| findstr LISTENING') do taskkill /PID %%a /F >nul 2>&1

echo.
echo   [BE] Backend:  http://localhost:8899
echo   [WK] Worker:   Task executor (independent process)
echo   [FE] Frontend: http://localhost:8888
echo.

cd /d %~dp0
pnpm dev
