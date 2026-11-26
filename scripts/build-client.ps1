$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    & .\.venv\Scripts\flet.exe pack client_app.py -D -n DNTSNE-ModSync --distpath dist/0.1.3 --product-name 'Loadout ModSync' --product-version 0.1.3 --file-version 0.1.3.0 -y
    if ($LASTEXITCODE -ne 0) { throw 'flet pack failed' }
    $smoke = Start-Process -FilePath '.\dist\0.1.3\DNTSNE-ModSync\DNTSNE-ModSync.exe' -ArgumentList '--self-test' -WindowStyle Hidden -Wait -PassThru
    if ($smoke.ExitCode -ne 0) { throw 'Portable smoke test failed' }
} finally { Pop-Location }

