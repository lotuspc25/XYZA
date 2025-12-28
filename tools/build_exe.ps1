param()
$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptRoot "..")
Set-Location $repoRoot

if (-not $env:CONDA_DEFAULT_ENV) {
    Write-Warning "Conda environment is not active; continuing with current Python."
}

$specPath = Join-Path $repoRoot "build\xyza.spec"
if (-not (Test-Path $specPath)) {
    Write-Error "Spec not found: $specPath"
    exit 1
}

python -m PyInstaller $specPath --noconfirm --clean

# Verify build via doctor
python tools/build_doctor.py
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if (Test-Path "dist\XYZA.exe") {
    Write-Host "Build OK: dist\XYZA.exe"
} elseif (Test-Path "dist\XYZA\XYZA.exe") {
    Write-Host "Build OK: dist\XYZA\XYZA.exe"
} else {
    Write-Warning "Build finished but XYZA.exe not found. See build\build_log.txt"
    exit 1
}
