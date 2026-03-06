#Requires -Version 5.1
<#
.SYNOPSIS
    Aegis One-Click Installer for Windows
.DESCRIPTION
    Installs all dependencies (Git, Python, Node.js, AI CLIs) and sets up the Aegis project.
    Designed for non-technical users on Windows 10/11.
#>

param(
    [string]$RootDir = "",
    [string]$InstallDir = ""
)

# ============================================================
# Configuration
# ============================================================
# Use "Continue" globally — external tools (git, pip, npm) write progress
# to stderr which PowerShell would otherwise treat as terminating errors.
# Actual failures are caught via $LASTEXITCODE and try/catch.
$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"  # Speed up Invoke-WebRequest

$REPO_URL = "https://github.com/cwen0708/aegis.git"
$BACKEND_PORT = 8899
$FRONTEND_PORT = 5173

# ============================================================
# Helpers
# ============================================================
$LogFile = ""

function Write-Step {
    param([string]$Message, [string]$Status = "...")
    $timestamp = Get-Date -Format "HH:mm:ss"
    $line = "[$timestamp] $Message"
    Write-Host "  $line" -ForegroundColor Cyan
    if ($LogFile) { Add-Content -Path $LogFile -Value $line -Encoding UTF8 }
}

function Write-OK {
    param([string]$Message)
    Write-Host "  [OK] $Message" -ForegroundColor Green
    if ($LogFile) { Add-Content -Path $LogFile -Value "[OK] $Message" -Encoding UTF8 }
}

function Write-Warn {
    param([string]$Message)
    Write-Host "  [!] $Message" -ForegroundColor Yellow
    if ($LogFile) { Add-Content -Path $LogFile -Value "[WARN] $Message" -Encoding UTF8 }
}

function Write-Err {
    param([string]$Message)
    Write-Host "  [X] $Message" -ForegroundColor Red
    if ($LogFile) { Add-Content -Path $LogFile -Value "[ERROR] $Message" -Encoding UTF8 }
}

function Write-Banner {
    Write-Host ""
    Write-Host "  ============================================" -ForegroundColor Magenta
    Write-Host "       Aegis Installer v1.0" -ForegroundColor Magenta
    Write-Host "       AI Engineering Grid & Intelligence" -ForegroundColor Magenta
    Write-Host "  ============================================" -ForegroundColor Magenta
    Write-Host ""
}

function Refresh-Path {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"
}

function Test-CommandExists {
    param([string]$Command)
    $null = Get-Command $Command -ErrorAction SilentlyContinue
    return $?
}

function Get-WingetPath {
    # winget might not be in PATH in some contexts; search common locations
    $candidates = @(
        "winget",
        "$env:LOCALAPPDATA\Microsoft\WindowsApps\winget.exe",
        "C:\Program Files\WindowsApps\Microsoft.DesktopAppInstaller_*\winget.exe"
    )
    foreach ($c in $candidates) {
        if ($c -like "*`**") {
            $resolved = Get-Item $c -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($resolved) { return $resolved.FullName }
        } elseif (Test-CommandExists $c) {
            return $c
        } elseif (Test-Path $c) {
            return $c
        }
    }
    return $null
}

function Install-WithWinget {
    param(
        [string]$PackageId,
        [string]$Name,
        [string]$TestCommand,
        [string]$WingetExe
    )

    if ($TestCommand -and (Test-CommandExists $TestCommand)) {
        Write-OK "$Name 已安裝"
        return $true
    }

    Write-Step "正在安裝 $Name ..."
    try {
        $result = & $WingetExe install --id $PackageId --accept-source-agreements --accept-package-agreements --silent 2>&1
        $exitCode = $LASTEXITCODE

        # Refresh PATH after install
        Refresh-Path

        if ($exitCode -eq 0 -or $exitCode -eq -1978335189) {
            # -1978335189 = already installed
            Write-OK "$Name 安裝完成"
            return $true
        } else {
            Write-Warn "$Name 安裝可能有問題 (exit code: $exitCode)"
            Write-Warn ($result | Out-String)
            return $false
        }
    } catch {
        Write-Err "安裝 $Name 失敗: $_"
        return $false
    }
}

# ============================================================
# Main Installation
# ============================================================
function Start-Installation {
    Write-Banner

    # ----------------------------------------------------------
    # Step 0: Determine install directory
    # ----------------------------------------------------------
    $isInsideRepo = $false
    if ($RootDir -and (Test-Path (Join-Path $RootDir ".git"))) {
        $isInsideRepo = $true
        $projectDir = (Resolve-Path $RootDir).Path.TrimEnd('\')
    } elseif ($InstallDir) {
        $projectDir = $InstallDir
    } else {
        $defaultDir = Join-Path $env:USERPROFILE "Aegis"
        Write-Host "  安裝目錄 (直接 Enter 使用預設):" -ForegroundColor White
        Write-Host "  預設: $defaultDir" -ForegroundColor Gray
        $userInput = Read-Host "  路徑"
        if ([string]::IsNullOrWhiteSpace($userInput)) {
            $projectDir = $defaultDir
        } else {
            $projectDir = $userInput
        }
    }

    # Set up log file
    $script:LogFile = Join-Path $projectDir "install.log"
    if (!(Test-Path $projectDir)) {
        New-Item -ItemType Directory -Path $projectDir -Force | Out-Null
    }
    "" | Set-Content -Path $LogFile -Encoding UTF8
    Write-Step "安裝目錄: $projectDir"
    Write-Step "記錄檔: $LogFile"

    # ----------------------------------------------------------
    # Step 1: Check Windows version & winget
    # ----------------------------------------------------------
    Write-Host ""
    Write-Host "  [1/7] 檢查系統環境" -ForegroundColor White
    Write-Host "  ─────────────────────────────────" -ForegroundColor DarkGray

    $osVersion = [System.Environment]::OSVersion.Version
    Write-Step "Windows 版本: $($osVersion.Major).$($osVersion.Minor).$($osVersion.Build)"

    if ($osVersion.Build -lt 17763) {
        Write-Err "需要 Windows 10 1809 或更新版本"
        return $false
    }

    # Check network
    try {
        $null = Invoke-WebRequest -Uri "https://www.google.com" -UseBasicParsing -TimeoutSec 5
        Write-OK "網路連線正常"
    } catch {
        Write-Err "無法連線到網路，請檢查網路設定"
        return $false
    }

    # Check winget
    $wingetExe = Get-WingetPath
    if (!$wingetExe) {
        Write-Err "找不到 winget。"
        Write-Err "Windows 11 應該已內建。Windows 10 請從 Microsoft Store 安裝「應用程式安裝程式」"
        Write-Host "  https://aka.ms/getwinget" -ForegroundColor Yellow
        return $false
    }
    Write-OK "winget 可用"

    # ----------------------------------------------------------
    # Step 2: Install Git, Python, Node.js via winget
    # ----------------------------------------------------------
    Write-Host ""
    Write-Host "  [2/7] 安裝基礎工具 (Git, Python, Node.js)" -ForegroundColor White
    Write-Host "  ─────────────────────────────────" -ForegroundColor DarkGray

    $gitOk = Install-WithWinget -PackageId "Git.Git" -Name "Git" -TestCommand "git" -WingetExe $wingetExe
    if (!$gitOk) {
        Write-Err "Git 安裝失敗，無法繼續"
        return $false
    }
    Refresh-Path

    $pythonOk = Install-WithWinget -PackageId "Python.Python.3.12" -Name "Python 3.12" -TestCommand "python" -WingetExe $wingetExe
    if (!$pythonOk) {
        Write-Err "Python 安裝失敗，無法繼續"
        return $false
    }
    Refresh-Path

    $nodeOk = Install-WithWinget -PackageId "OpenJS.NodeJS.LTS" -Name "Node.js LTS" -TestCommand "node" -WingetExe $wingetExe
    if (!$nodeOk) {
        Write-Err "Node.js 安裝失敗，無法繼續"
        return $false
    }
    Refresh-Path

    # Show versions
    try {
        $gitVer = & git --version 2>&1
        $pyVer = & python --version 2>&1
        $nodeVer = & node --version 2>&1
        Write-Step "版本: $gitVer | $pyVer | Node $nodeVer"
    } catch {}

    # ----------------------------------------------------------
    # Step 3: Clone repository
    # ----------------------------------------------------------
    Write-Host ""
    Write-Host "  [3/7] 取得 Aegis 原始碼" -ForegroundColor White
    Write-Host "  ─────────────────────────────────" -ForegroundColor DarkGray

    if ($isInsideRepo) {
        Write-OK "已在專案目錄中，跳過 clone"
    } elseif (Test-Path (Join-Path $projectDir ".git")) {
        Write-OK "專案已存在，執行 git pull"
        Push-Location $projectDir
        $null = & git pull --ff-only 2>&1
        Pop-Location
    } else {
        Write-Step "正在 clone 專案..."
        # If directory exists but is not a git repo (e.g. created for install.log),
        # clone into a temp dir then move contents
        if (Test-Path $projectDir) {
            $tempClone = "$projectDir-clone-tmp"
            if (Test-Path $tempClone) { Remove-Item -Recurse -Force $tempClone }
            $null = & git clone $REPO_URL $tempClone 2>&1
            if ($LASTEXITCODE -ne 0) {
                Write-Err "git clone 失敗"
                return $false
            }
            # Move everything from temp into project dir
            Get-ChildItem -Path $tempClone -Force | Move-Item -Destination $projectDir -Force
            Remove-Item -Recurse -Force $tempClone
        } else {
            $null = & git clone $REPO_URL $projectDir 2>&1
            if ($LASTEXITCODE -ne 0) {
                Write-Err "git clone 失敗"
                return $false
            }
        }
        Write-OK "Clone 完成"
    }

    # ----------------------------------------------------------
    # Step 4: Backend setup
    # ----------------------------------------------------------
    Write-Host ""
    Write-Host "  [4/7] 設定後端 (Python + FastAPI)" -ForegroundColor White
    Write-Host "  ─────────────────────────────────" -ForegroundColor DarkGray

    $backendDir = Join-Path $projectDir "backend"
    $venvDir = Join-Path $backendDir "venv"
    $venvPython = Join-Path $venvDir "Scripts\python.exe"
    $venvPip = Join-Path $venvDir "Scripts\pip.exe"

    if (!(Test-Path $venvDir)) {
        Write-Step "建立 Python 虛擬環境..."
        & python -m venv $venvDir 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Err "建立 venv 失敗"
            return $false
        }
    }
    Write-OK "虛擬環境就緒"

    Write-Step "安裝 Python 套件..."
    $null = & $venvPip install -q -r (Join-Path $backendDir "requirements.txt") 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "部分 Python 套件安裝可能有問題，但嘗試繼續"
    } else {
        Write-OK "Python 套件安裝完成"
    }

    # Seed database if no local.db exists
    $dbPath = Join-Path $backendDir "local.db"
    if (!(Test-Path $dbPath)) {
        Write-Step "初始化資料庫..."
        Push-Location $backendDir
        & $venvPython seed.py 2>&1
        Pop-Location
        Write-OK "資料庫初始化完成"
    } else {
        Write-OK "資料庫已存在"
    }

    # ----------------------------------------------------------
    # Step 5: Frontend setup
    # ----------------------------------------------------------
    Write-Host ""
    Write-Host "  [5/7] 設定前端 (Vue 3 + Vite)" -ForegroundColor White
    Write-Host "  ─────────────────────────────────" -ForegroundColor DarkGray

    $frontendDir = Join-Path $projectDir "frontend"

    # Install pnpm if not available
    if (!(Test-CommandExists "pnpm")) {
        Write-Step "安裝 pnpm..."
        & npm install -g pnpm 2>&1 | Out-Null
        Refresh-Path
    }

    Write-Step "安裝前端套件 (這可能需要幾分鐘)..."
    Push-Location $frontendDir
    & pnpm install 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "pnpm install 失敗，嘗試使用 npm..."
        & npm install 2>&1
    }
    Pop-Location
    Write-OK "前端套件安裝完成"

    # ----------------------------------------------------------
    # Step 6: AI CLIs (optional)
    # ----------------------------------------------------------
    Write-Host ""
    Write-Host "  [6/7] 安裝 AI 工具 (選用，失敗不影響)" -ForegroundColor White
    Write-Host "  ─────────────────────────────────" -ForegroundColor DarkGray

    # Claude Code CLI
    if (Test-CommandExists "claude") {
        Write-OK "Claude Code CLI 已安裝"
    } else {
        Write-Step "安裝 Claude Code CLI..."
        try {
            & npm install -g @anthropic-ai/claude-code 2>&1
            Refresh-Path
            if (Test-CommandExists "claude") {
                Write-OK "Claude Code CLI 安裝完成"
            } else {
                Write-Warn "Claude Code CLI 安裝完成但無法在 PATH 中找到，請重新開啟終端機"
            }
        } catch {
            Write-Warn "Claude Code CLI 安裝失敗（不影響核心功能）"
        }
    }

    # Gemini CLI
    if (Test-CommandExists "gemini") {
        Write-OK "Gemini CLI 已安裝"
    } else {
        Write-Step "安裝 Gemini CLI..."
        try {
            & npm install -g @google/gemini-cli 2>&1
            Refresh-Path
            if (Test-CommandExists "gemini") {
                Write-OK "Gemini CLI 安裝完成"
            } else {
                Write-Warn "Gemini CLI 安裝完成但無法在 PATH 中找到，請重新開啟終端機"
            }
        } catch {
            Write-Warn "Gemini CLI 安裝失敗（不影響核心功能）"
        }
    }

    # ----------------------------------------------------------
    # Step 7: Create launcher & shortcuts
    # ----------------------------------------------------------
    Write-Host ""
    Write-Host "  [7/7] 建立啟動捷徑" -ForegroundColor White
    Write-Host "  ─────────────────────────────────" -ForegroundColor DarkGray

    # Create start-aegis.bat in project root
    $startScript = Join-Path $projectDir "start-aegis.bat"
    $startContent = @"
@echo off
chcp 65001 >nul 2>&1
title Aegis
echo.
echo  Starting Aegis...
echo.

set "PROJECT_DIR=%~dp0"

:: Start backend
echo  [1/3] Starting backend server...
start "Aegis Backend" /min cmd /c "cd /d "%PROJECT_DIR%backend" && venv\Scripts\activate && python -m uvicorn app.main:app --host 127.0.0.1 --port $BACKEND_PORT"

:: Wait for backend to be ready
echo  [2/3] Waiting for backend...
:wait_backend
timeout /t 2 /nobreak >nul
powershell -Command "try { `$r = Invoke-WebRequest -Uri 'http://127.0.0.1:$BACKEND_PORT/health' -UseBasicParsing -TimeoutSec 2; if (`$r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
if %ERRORLEVEL% NEQ 0 goto wait_backend
echo  [OK] Backend is ready

:: Start frontend
echo  [3/3] Starting frontend...
start "Aegis Frontend" /min cmd /c "cd /d "%PROJECT_DIR%frontend" && npx vite --host 127.0.0.1 --port $FRONTEND_PORT"

:: Wait a moment for frontend to start
timeout /t 3 /nobreak >nul

:: Open browser
start http://localhost:$FRONTEND_PORT

echo.
echo  ╔══════════════════════════════════════╗
echo  ║  Aegis is running!                   ║
echo  ║                                      ║
echo  ║  Frontend: http://localhost:$FRONTEND_PORT     ║
echo  ║  Backend:  http://localhost:$BACKEND_PORT      ║
echo  ║                                      ║
echo  ║  Close this window to stop Aegis.    ║
echo  ╚══════════════════════════════════════╝
echo.
echo  Press any key to stop all services...
pause >nul

:: Kill background processes
taskkill /fi "WINDOWTITLE eq Aegis Backend" /f >nul 2>&1
taskkill /fi "WINDOWTITLE eq Aegis Frontend" /f >nul 2>&1
echo  Aegis stopped.
"@
    Set-Content -Path $startScript -Value $startContent -Encoding UTF8
    Write-OK "啟動腳本已建立: start-aegis.bat"

    # Create desktop shortcut
    try {
        $desktopPath = [Environment]::GetFolderPath("Desktop")
        $shortcutPath = Join-Path $desktopPath "Aegis.lnk"

        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath = $startScript
        $shortcut.WorkingDirectory = $projectDir
        $shortcut.Description = "Launch Aegis - AI Engineering Grid & Intelligence System"
        $shortcut.WindowStyle = 1  # Normal window

        # Use a custom icon if available, otherwise use default
        $iconPath = Join-Path $projectDir "frontend\public\favicon.ico"
        if (Test-Path $iconPath) {
            $shortcut.IconLocation = $iconPath
        }

        $shortcut.Save()
        Write-OK "桌面捷徑已建立: Aegis.lnk"
    } catch {
        Write-Warn "建立桌面捷徑失敗: $_"
        Write-Warn "你可以手動執行 $startScript 來啟動 Aegis"
    }

    # ----------------------------------------------------------
    # Done!
    # ----------------------------------------------------------
    Write-Host ""
    Write-Host "  ============================================" -ForegroundColor Green
    Write-Host "       安裝完成！" -ForegroundColor Green
    Write-Host "  ============================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  啟動方式:" -ForegroundColor White
    Write-Host "    1. 雙擊桌面上的「Aegis」捷徑" -ForegroundColor Gray
    Write-Host "    2. 或執行 $startScript" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  首次使用提示:" -ForegroundColor White
    Write-Host "    - Gemini API Key 可在 Settings 頁面設定" -ForegroundColor Gray
    Write-Host "    - Claude / Gemini CLI 登入請在終端機執行:" -ForegroundColor Gray
    Write-Host "      claude login" -ForegroundColor Yellow
    Write-Host "      gemini auth login" -ForegroundColor Yellow
    Write-Host ""

    return $true
}

# ============================================================
# Entry point
# ============================================================
try {
    $result = Start-Installation
    if ($result) {
        exit 0
    } else {
        Write-Host ""
        Write-Err "安裝失敗，請查看上方錯誤訊息或 install.log"
        exit 1
    }
} catch {
    Write-Err "未預期的錯誤: $_"
    Write-Err $_.ScriptStackTrace
    exit 1
}
