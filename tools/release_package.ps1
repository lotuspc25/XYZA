$ErrorActionPreference = "Stop"

function Find-Root {
    $here = Split-Path -Parent $MyInvocation.MyCommand.Path
    return (Resolve-Path (Join-Path $here "..")).Path
}

$root = Find-Root
$distDir = Join-Path $root "dist"
$exeCandidates = @(
    (Join-Path $distDir "XYZA\XYZA.exe"),
    (Join-Path $distDir "XYZA.exe")
)

$exePath = $null
foreach ($c in $exeCandidates) {
    if (Test-Path $c) { $exePath = $c; break }
}

if (-not $exePath) {
    Write-Error "XYZA.exe bulunamadı. Önce build/xyza.spec ile PyInstaller build çalıştırın."
}

$releaseRoot = Join-Path $root "release"
$portableDir = Join-Path $releaseRoot "XYZA_Portable"
$zipPath = Join-Path $releaseRoot "XYZA_Portable_v0.1.0.zip"

if (-not (Test-Path $releaseRoot)) {
    New-Item -ItemType Directory -Path $releaseRoot | Out-Null
}
if (Test-Path $portableDir) {
    Remove-Item -Recurse -Force $portableDir
}
New-Item -ItemType Directory -Path $portableDir | Out-Null

Copy-Item -Path $exePath -Destination (Join-Path $portableDir "XYZA.exe")

function Copy-IfExists($src, $destDir) {
    if (Test-Path $src) {
        Copy-Item -Path $src -Destination $destDir -Force
        return $true
    }
    return $false
}

$copiedSettings = Copy-IfExists (Join-Path $root "default_settings.ini") $portableDir
$copiedTools = Copy-IfExists (Join-Path $root "default_tool.ini") $portableDir

if (-not $copiedSettings) {
    Copy-IfExists (Join-Path $root "resources" "default_settings.ini") $portableDir | Out-Null
}
if (-not $copiedTools) {
    Copy-IfExists (Join-Path $root "resources" "default_tool.ini") $portableDir | Out-Null
}

if (Test-Path $zipPath) {
    Remove-Item -Force $zipPath
}
Compress-Archive -Path (Join-Path $portableDir "*") -DestinationPath $zipPath

Write-Host "Portable paket oluşturuldu:" $zipPath
