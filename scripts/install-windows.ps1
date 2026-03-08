# Aegis Windows Installation Script
# Usage: irm https://raw.githubusercontent.com/cwen0708/aegis/refs/heads/main/scripts/install-windows.ps1 | iex
# Or: .\install-windows.ps1 [-InstallDir "C:\Aegis"] [-SkipCLI] [-Dev]

param(
    [string]$InstallDir = "$env:LOCALAPPDATA\Aegis",
    [switch]$SkipCLI,
    [switch]$Dev,
    [switch]$Help
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# Colors
function Write-Step { param($msg) Write-Host "`n[*] $msg" -ForegroundColor Cyan }
function Write-Success { param($msg) Write-Host "[+] $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "[!] $msg" -ForegroundColor Yellow }
function Write-Err { param($msg) Write-Host "[-] $msg" -ForegroundColor Red }

if ($Help) {
    Write-Host @"
Aegis Installation Script for Windows

Usage:
    .\install-windows.ps1 [options]

Options:
    -InstallDir <path>   Installation directory (default: %LOCALAPPDATA%\Aegis)
    -SkipCLI             Skip Claude CLI and Gemini CLI installation
    -Dev                 Clone with git instead of downloading release
    -Help                Show this help message

Examples:
    .\install-windows.ps1
    .\install-windows.ps1 -InstallDir "D:\Tools\Aegis"
    .\install-windows.ps1 -SkipCLI -Dev
"@
    exit 0
}

Write-Host @"

    _    _____ ____ ___ ____
   / \  | ____/ ___|_ _/ ___|
  / _ \ |  _|| |  _ | |\___ \
 / ___ \| |__| |_| || | ___) |
/_/   \_\_____\____|___|____/

  AI Agent Management Dashboard

"@ -ForegroundColor Cyan

# ============================================
# Check Prerequisites
# ============================================
Write-Step "Checking prerequisites..."

# Check Node.js
$nodeVersion = $null
try {
    $nodeVersion = (node --version 2>$null)
} catch {}

if (-not $nodeVersion) {
    Write-Err "Node.js not found. Please install Node.js 18+ from https://nodejs.org/"
    Write-Host "  Or use winget: winget install OpenJS.NodeJS.LTS"
    exit 1
}
Write-Success "Node.js: $nodeVersion"

# Check npm
$npmVersion = (npm --version 2>$null)
if (-not $npmVersion) {
    Write-Err "npm not found"
    exit 1
}
Write-Success "npm: $npmVersion"

# Check Python
$pythonCmd = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>$null
        if ($ver -match "Python 3\.(\d+)") {
            $minor = [int]$Matches[1]
            if ($minor -ge 10) {
                $pythonCmd = $cmd
                Write-Success "Python: $ver"
                break
            }
        }
    } catch {}
}

if (-not $pythonCmd) {
    Write-Err "Python 3.10+ not found. Please install Python from https://python.org/"
    Write-Host "  Or use winget: winget install Python.Python.3.12"
    exit 1
}

# Check Git (only for Dev mode)
if ($Dev) {
    $gitVersion = (git --version 2>$null)
    if (-not $gitVersion) {
        Write-Err "Git not found. Required for -Dev mode."
        Write-Host "  Install from https://git-scm.com/ or: winget install Git.Git"
        exit 1
    }
    Write-Success "Git: $gitVersion"
}

# ============================================
# Create Installation Directory
# ============================================
Write-Step "Setting up installation directory..."

if (Test-Path $InstallDir) {
    Write-Warn "Directory exists: $InstallDir"
    $confirm = Read-Host "Overwrite? (y/N)"
    if ($confirm -ne "y" -and $confirm -ne "Y") {
        Write-Host "Aborted."
        exit 0
    }
}

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Set-Location $InstallDir
Write-Success "Install directory: $InstallDir"

# ============================================
# Download or Clone Aegis
# ============================================
Write-Step "Downloading Aegis..."

if ($Dev) {
    # Clone from GitHub
    if (Test-Path ".git") {
        Write-Host "  Updating existing repository..."
        git pull
    } else {
        git clone https://github.com/cwen0708/aegis.git .
    }
} else {
    # Download latest release
    $releaseUrl = "https://github.com/cwen0708/aegis/archive/refs/heads/main.zip"
    $zipPath = "$env:TEMP\aegis-main.zip"

    Write-Host "  Downloading from GitHub..."
    Invoke-WebRequest -Uri $releaseUrl -OutFile $zipPath

    Write-Host "  Extracting..."
    Expand-Archive -Path $zipPath -DestinationPath $env:TEMP -Force

    # Move contents from extracted folder (GitHub uses lowercase repo name)
    $extractedDir = Get-ChildItem "$env:TEMP" -Directory -Filter "aegis-*" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $extractedDir) {
        $extractedDir = Get-ChildItem "$env:TEMP" -Directory -Filter "Aegis-*" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    }
    if (-not $extractedDir) {
        Write-Err "Failed to find extracted Aegis folder"
        exit 1
    }
    Get-ChildItem "$($extractedDir.FullName)\*" | Move-Item -Destination $InstallDir -Force

    Remove-Item $zipPath -Force
    Remove-Item $extractedDir.FullName -Force -Recurse -ErrorAction SilentlyContinue
}

Write-Success "Aegis downloaded"

# ============================================
# Setup Backend (Python)
# ============================================
Write-Step "Setting up backend..."

Set-Location "$InstallDir\backend"

# Create virtual environment
Write-Host "  Creating Python virtual environment..."
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $pythonCmd -m venv venv 2>&1 | ForEach-Object { "$_" }
$ErrorActionPreference = $prevEAP
if (-not (Test-Path ".\venv\Scripts\python.exe")) { throw "venv creation failed" }

# Activate and install dependencies
# pip emits warnings to stderr; prevent PowerShell from treating them as errors
Write-Host "  Installing Python dependencies..."
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& ".\venv\Scripts\pip.exe" install -q -r requirements.txt 2>&1 | ForEach-Object { "$_" }
$ErrorActionPreference = $prevEAP
if (-not (Test-Path ".\venv\Scripts\pip.exe")) { throw "pip install failed" }

Write-Success "Backend ready"

# ============================================
# Setup Frontend (Node.js)
# ============================================
Write-Step "Setting up frontend..."

Set-Location "$InstallDir\frontend"

# npm commands emit warnings to stderr; prevent PowerShell from treating them as errors
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"

Write-Host "  Installing npm dependencies..."
npm install --force 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Warn "npm install had issues, retrying with clean install..."
    Remove-Item -Recurse -Force node_modules -ErrorAction SilentlyContinue
    npm install --force 2>$null
}

Write-Host "  Building frontend..."
npm run build 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Err "Frontend build failed. You can retry later with: cd frontend && npm run build"
    Write-Warn "Continuing installation..."
}

$ErrorActionPreference = $prevEAP

Write-Success "Frontend ready"

# ============================================
# Install CLI Tools (Optional)
# ============================================
if (-not $SkipCLI) {
    Write-Step "Installing AI CLI tools..."

    # npm global installs emit deprecation warnings to stderr which
    # PowerShell treats as terminating errors under $ErrorActionPreference=Stop
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"

    Write-Host "  Installing Claude CLI..."
    npm install -g @anthropic-ai/claude-code 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Success "Claude CLI installed"
    } else {
        Write-Warn "Claude CLI installation failed (you can install it later)"
    }

    Write-Host "  Installing Gemini CLI..."
    npm install -g @google/gemini-cli 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Success "Gemini CLI installed"
    } else {
        Write-Warn "Gemini CLI installation failed (you can install it later)"
    }

    $ErrorActionPreference = $prevEAP
}

# ============================================
# Create Startup Script
# ============================================
Write-Step "Creating startup scripts..."

Set-Location $InstallDir

# Create start script
$startScript = @"
@echo off
title Aegis Server
cd /d "$InstallDir\backend"
call venv\Scripts\activate.bat
python -m uvicorn app.main:app --host 127.0.0.1 --port 8899
"@
Set-Content -Path "start-aegis.bat" -Value $startScript

# Create desktop shortcut
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("$env:USERPROFILE\Desktop\Aegis.lnk")
$Shortcut.TargetPath = "$InstallDir\start-aegis.bat"
$Shortcut.WorkingDirectory = $InstallDir
$Shortcut.Description = "Start Aegis Server"
$Shortcut.Save()

Write-Success "Created start-aegis.bat"
Write-Success "Created desktop shortcut"

# ============================================
# Done!
# ============================================
Write-Host "`n" + "=" * 50 -ForegroundColor Green
Write-Host "  Installation Complete!" -ForegroundColor Green
Write-Host "=" * 50 -ForegroundColor Green

Write-Host @"

To start Aegis:
  1. Double-click the 'Aegis' shortcut on your desktop
  2. Or run: $InstallDir\start-aegis.bat
  3. Open http://localhost:8899 in your browser

Configuration:
  - Install directory: $InstallDir
  - Backend: $InstallDir\backend
  - Frontend: $InstallDir\frontend
  - Database: $InstallDir\backend\local.db

Next steps:
  1. Start the server
  2. Complete the onboarding wizard
  3. Add your AI accounts (Claude/Gemini)
  4. Create projects and start automating!

"@ -ForegroundColor White

# Ask if user wants to start now
$startNow = Read-Host "Start Aegis now? (Y/n)"
if ($startNow -ne "n" -and $startNow -ne "N") {
    Start-Process "$InstallDir\start-aegis.bat"
    Start-Sleep -Seconds 3
    Start-Process "http://localhost:8899"
}
