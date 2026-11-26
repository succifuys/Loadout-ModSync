param([string]$Python)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'windows-build-common.ps1')
Push-Location $projectRoot
try {
    $pythonExe = Get-BuildPython $Python
    $version = Get-ModSyncVersion $pythonExe
    $dist = Join-Path $projectRoot 'dist'
    $exe = Join-Path $dist 'Loadout-ModSync.exe'
    if (Test-Path -LiteralPath $exe) { throw 'Move the previous dist/Loadout-ModSync.exe out of dist first.' }
    $flet = Join-Path (Split-Path -Parent $pythonExe) 'flet.exe'
    & $flet pack client_app.py -n Loadout-ModSync --distpath $dist --product-name 'Loadout ModSync' --product-version $version --file-version "$version.0" -y
    if ($LASTEXITCODE -ne 0) { throw 'Single EXE build failed.' }
    Test-ModSyncBuild $exe
    & $pythonExe scripts/collect-notices.py (Join-Path $dist 'THIRD-PARTY-LICENSES')
    if ($LASTEXITCODE -ne 0) { throw 'Could not collect license notices.' }
    Get-FileHash -LiteralPath $exe -Algorithm SHA256
} finally { Pop-Location }
