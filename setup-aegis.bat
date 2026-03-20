@echo off
title Aegis Installer
echo.
echo  ========================================
echo        Aegis - One-Click Setup
echo  ========================================
echo.

set "SCRIPT_DIR=%~dp0"
set "PS_SCRIPT=%SCRIPT_DIR%scripts\install.ps1"
set "DOWNLOAD_URL=https://raw.githubusercontent.com/cwen0708/aegis/main/scripts/install.ps1"

if exist "%PS_SCRIPT%" (
    echo  [*] Using local install script...
    goto run_installer
)

echo  [*] Downloading install script...
set "PS_SCRIPT=%TEMP%\aegis-install.ps1"
curl -fsSL -o "%PS_SCRIPT%" "%DOWNLOAD_URL%" >nul 2>&1

if not exist "%PS_SCRIPT%" (
    echo.
    echo  [X] Failed to download install script.
    echo  [!] Manual download: %DOWNLOAD_URL%
    echo.
    pause
    exit /b 1
)
echo  [OK] Download complete
echo.

:run_installer
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PS_SCRIPT%"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  [!] Installation error. Check install.log for details.
    echo.
    pause
    exit /b 1
)

echo.
echo  Installation complete! Press any key to close...
pause >nul
