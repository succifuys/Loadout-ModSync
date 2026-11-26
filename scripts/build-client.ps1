param([string]$Python)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'windows-build-common.ps1')
Push-Location $projectRoot
try {
    $pythonExe = Get-BuildPython $Python
    $version = Get-ModSyncVersion $pythonExe
    $output = Join-Path $projectRoot "dist/$version"
    $bundle = Join-Path $output 'DNTSNE-ModSync'
    if (Test-Path -LiteralPath $bundle) { throw "Move the existing portable build out of $output first." }
    $flet = Join-Path (Split-Path -Parent $pythonExe) 'flet.exe'
    & $flet pack client_app.py -D -n DNTSNE-ModSync --distpath $output --product-name 'Loadout ModSync' --product-version $version --file-version "$version.0" -y
    if ($LASTEXITCODE -ne 0) { throw 'Portable build failed.' }
    if (!(Test-Path -LiteralPath (Join-Path $bundle '_internal') -PathType Container)) { throw 'Portable build is missing _internal.' }
    Test-ModSyncBuild (Join-Path $bundle 'DNTSNE-ModSync.exe')
    & $pythonExe scripts/collect-notices.py (Join-Path $bundle 'THIRD-PARTY-LICENSES')
    if ($LASTEXITCODE -ne 0) { throw 'Could not collect license notices.' }
} finally { Pop-Location }
