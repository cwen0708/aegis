@echo off
chcp 65001 >nul 2>&1
title Aegis Installer
echo.
echo  ╔══════════════════════════════════════╗
echo  ║       Aegis - One-Click Setup        ║
echo  ╚══════════════════════════════════════╝
echo.

:: Determine script location
set "SCRIPT_DIR=%~dp0"
set "PS_SCRIPT=%SCRIPT_DIR%scripts\install.ps1"
set "DOWNLOAD_URL=https://ai-aegis.web.app/scripts/install.ps1"

:: Check if install.ps1 exists locally (running from cloned repo)
if exist "%PS_SCRIPT%" (
    echo  [*] 使用本地安裝腳本...
    goto :run_installer
)

:: Download install.ps1 from web (suppress PowerShell output, show our own message)
echo  [*] 下載安裝腳本...
set "PS_SCRIPT=%TEMP%\aegis-install.ps1"

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
    "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%DOWNLOAD_URL%' -OutFile '%PS_SCRIPT%' -UseBasicParsing" >nul 2>&1

if not exist "%PS_SCRIPT%" (
    echo.
    echo  [X] 無法下載安裝腳本，請確認網路連線
    echo  [!] 或手動下載: %DOWNLOAD_URL%
    echo.
    pause
    exit /b 1
)
echo  [OK] 下載完成
echo.

:run_installer
:: Launch PowerShell with bypass policy
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PS_SCRIPT%"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  [!] 安裝過程發生錯誤，請查看 install.log
    echo.
    pause
    exit /b 1
)

echo.
echo  安裝完成！按任意鍵關閉...
pause >nul
