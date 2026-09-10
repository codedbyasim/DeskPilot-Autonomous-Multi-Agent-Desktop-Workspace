<#
.SYNOPSIS
    DeskPilot Build Pipeline — PyInstaller & Inno Setup
.DESCRIPTION
    Builds the standalone DeskPilot distribution using PyInstaller and
    optionally packages it into a native Windows installer using Inno Setup.
#>

[CmdletBinding()]
param (
    [switch]$SkipInstaller,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectRoot = Resolve-Path "$ScriptDir\.."

Write-Host "`n=======================================================" -ForegroundColor Cyan
Write-Host "       DeskPilot Build Pipeline (v2.0.0)              " -ForegroundColor Cyan
Write-Host "=======================================================`n" -ForegroundColor Cyan

Set-Location $ProjectRoot

# 1. Clean previous builds if requested
if ($Clean) {
    Write-Host "[1/4] Cleaning build artifacts..." -ForegroundColor Yellow
    if (Test-Path "$ProjectRoot\build") { Remove-Item -Recurse -Force "$ProjectRoot\build" }
    if (Test-Path "$ProjectRoot\dist\DeskPilot") { Remove-Item -Recurse -Force "$ProjectRoot\dist\DeskPilot" }
    Write-Host "       Previous builds cleaned successfully." -ForegroundColor Green
} else {
    Write-Host "[1/4] Checking build directories..." -ForegroundColor Yellow
}

# 2. Check PyInstaller
Write-Host "`n[2/4] Verifying PyInstaller environment..." -ForegroundColor Yellow
try {
    $pyinstallerVersion = python -m PyInstaller --version 2>&1
    Write-Host "       PyInstaller version: $pyinstallerVersion" -ForegroundColor Green
} catch {
    Write-Host "       PyInstaller not found. Installing via pip..." -ForegroundColor Yellow
    python -m pip install pyinstaller
}

# 3. Run PyInstaller
Write-Host "`n[3/4] Running PyInstaller build (deskpilot.spec)..." -ForegroundColor Yellow
python -m PyInstaller "$ProjectRoot\deskpilot.spec" --noconfirm

$ExePath = "$ProjectRoot\dist\DeskPilot\DeskPilot.exe"
if (Test-Path $ExePath) {
    $ExeSize = (Get-Item $ExePath).Length / 1MB
    Write-Host "       SUCCESS: DeskPilot.exe generated ($([math]::Round($ExeSize, 2)) MB)" -ForegroundColor Green
    Write-Host "       Directory: $ProjectRoot\dist\DeskPilot" -ForegroundColor Gray
} else {
    Write-Host "       ERROR: DeskPilot.exe was not created!" -ForegroundColor Red
    exit 1
}

# 4. Inno Setup Packaging
Write-Host "`n[4/4] Inno Setup Installer packaging..." -ForegroundColor Yellow
if ($SkipInstaller) {
    Write-Host "       Skipping installer packaging (--SkipInstaller flag set)." -ForegroundColor DarkGray
} else {
    $IsccCandidates = @(
        "iscc",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )

    $IsccPath = $null
    foreach ($candidate in $IsccCandidates) {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) {
            $IsccPath = $candidate
            break
        } elseif (Test-Path $candidate) {
            $IsccPath = $candidate
            break
        }
    }

    if ($IsccPath) {
        Write-Host "       Found Inno Setup Compiler at: $IsccPath" -ForegroundColor Green
        Write-Host "       Compiling installer/deskpilot_setup.iss..." -ForegroundColor Yellow
        & $IsccPath "$ProjectRoot\installer\deskpilot_setup.iss"
        
        $InstallerPath = "$ProjectRoot\dist\installer\DeskPilot-Setup-v2.0.0.exe"
        if (Test-Path $InstallerPath) {
            $InstSize = (Get-Item $InstallerPath).Length / 1MB
            Write-Host "`n=======================================================" -ForegroundColor Green
            Write-Host " BUILD COMPLETE: $InstallerPath ($([math]::Round($InstSize, 2)) MB)" -ForegroundColor Green
            Write-Host "=======================================================`n" -ForegroundColor Green
        }
    } else {
        Write-Host "       [INFO] Inno Setup compiler (iscc.exe) not found on PATH." -ForegroundColor Cyan
        Write-Host "       The standalone application is ready in: dist\DeskPilot\DeskPilot.exe" -ForegroundColor Green
        Write-Host "       To build the single-file setup installer:" -ForegroundColor Yellow
        Write-Host "       1. Download Inno Setup 6 from: https://jrsoftware.org/isdl.php" -ForegroundColor Gray
        Write-Host "       2. Run: iscc installer\deskpilot_setup.iss" -ForegroundColor Gray
    }
}

Write-Host "`nDone!" -ForegroundColor Cyan
