<#
.SYNOPSIS
    Build the Work Memory PyInstaller --onedir bundle and per-user Inno Setup installer.
.DESCRIPTION
    1. Generates packaging/work_memory.ico from the in-app programmatic icon.
    2. Packages src/work_memory/main.py using packaging/work_memory.spec (including SQL
       migrations and the offline faster-whisper base model unless -SkipModel is passed).
    3. Compiles packaging/work_memory.iss with Inno Setup 6 and outputs
       WorkMemorySetup-<version>.exe in the repository root folder.
#>
[CmdletBinding()]
param(
    [switch]$SkipModel,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    throw "Virtual environment Python not found at '$VenvPython'."
}

$Version = (& $VenvPython -c "import tomllib, pathlib; print(tomllib.loads(pathlib.Path(r'$Root\pyproject.toml').read_text(encoding='utf-8'))['project']['version'])").Trim()
if (-not $Version) {
    throw "Could not read project version from pyproject.toml."
}

Write-Host "=== Building Work Memory v$Version ===" -ForegroundColor Cyan

# 1. Generate multi-resolution icon matching the app/tray icon
& $VenvPython (Join-Path $Root "packaging\generate_icon.py")
if ($LASTEXITCODE -ne 0) {
    throw "Icon generation failed."
}

# 2. Verify PyInstaller is available in .venv
& $VenvPython -m PyInstaller --version | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is not installed in .venv. Run: .\.venv\Scripts\python.exe -m pip install pyinstaller"
}

if (-not $SkipModel) {
    $env:WM_REQUIRE_WHISPER_MODEL = "1"
} else {
    Remove-Item Env:WM_REQUIRE_WHISPER_MODEL -ErrorAction SilentlyContinue
}

# 3. Build --onedir bundle via PyInstaller
Push-Location $Root
try {
    & $VenvPython -m PyInstaller --clean --noconfirm (Join-Path $Root "packaging\work_memory.spec")
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed."
    }
} finally {
    Pop-Location
    Remove-Item Env:WM_REQUIRE_WHISPER_MODEL -ErrorAction SilentlyContinue
}

$DistExe = Join-Path $Root "dist\WorkMemory\WorkMemory.exe"
if (-not (Test-Path $DistExe)) {
    throw "Expected PyInstaller output not found at '$DistExe'."
}
Write-Host "PyInstaller bundle ready: $DistExe" -ForegroundColor Green

if ($SkipInstaller) {
    return
}

# 4. Locate Inno Setup Compiler (ISCC.exe)
$IsccCandidates = @(
    (Get-Command "iscc.exe" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) }

$Iscc = $IsccCandidates | Select-Object -First 1
if (-not $Iscc) {
    throw "Inno Setup 6 (ISCC.exe) was not found. Install it with: winget install --id JRSoftware.InnoSetup --source winget"
}

Write-Host "Compiling installer with: $Iscc" -ForegroundColor Cyan
& $Iscc "/DAppVersion=$Version" (Join-Path $Root "packaging\work_memory.iss")
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup compilation failed."
}

$InstallerExe = Join-Path $Root "WorkMemorySetup-$Version.exe"
if (-not (Test-Path $InstallerExe)) {
    throw "Expected installer executable not found at '$InstallerExe'."
}
Write-Host "Installer created at: $InstallerExe" -ForegroundColor Green
