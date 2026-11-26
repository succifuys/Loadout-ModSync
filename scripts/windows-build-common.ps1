$projectRoot = Split-Path -Parent $PSScriptRoot

function Get-BuildPython([string]$RequestedPython) {
    if (!$RequestedPython) {
        $RequestedPython = Join-Path $projectRoot '.venv/Scripts/python.exe'
        if (!(Test-Path -LiteralPath $RequestedPython -PathType Leaf)) {
            py -3 -m venv .venv | Out-Host
            if ($LASTEXITCODE -ne 0) { throw 'Install x64 Python 3.12+ before building.' }
        }
        & $RequestedPython -m pip install -r requirements-client.lock | Out-Host
        if ($LASTEXITCODE -ne 0) { throw 'Could not install the pinned build dependencies.' }
    }
    $resolvedPython = (Get-Command $RequestedPython -CommandType Application -ErrorAction Stop).Source
    & $resolvedPython -c "import sys,struct,platform; raise SystemExit(0 if sys.platform=='win32' and sys.version_info >= (3,12) and struct.calcsize('P') == 8 and platform.machine().lower() in ('amd64','x86_64') else 1)"
    if ($LASTEXITCODE -ne 0) { throw 'Windows x64 Python 3.12+ is required.' }
    $flet = Join-Path (Split-Path -Parent $resolvedPython) 'flet.exe'
    if (!(Test-Path -LiteralPath $flet -PathType Leaf)) { throw 'Install requirements-client.lock in this virtual environment first.' }
    return $resolvedPython
}

function Get-ModSyncVersion([string]$PythonExe) {
    $version = & $PythonExe -c "import pathlib,tomllib; print(tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8'))['project']['version'])"
    if ($LASTEXITCODE -ne 0 -or $version -notmatch '^\d+\.\d+\.\d+$') { throw 'Expected a three-part numeric project version.' }
    return $version
}

function Test-ModSyncBuild([string]$Exe) {
    if (!(Test-Path -LiteralPath $Exe -PathType Leaf)) { throw "Build output missing: $Exe" }
    $smoke = Start-Process -FilePath $Exe -ArgumentList '--self-test' -WindowStyle Hidden -Wait -PassThru
    if ($smoke.ExitCode -ne 0) { throw 'Packaged self-test failed.' }
}
