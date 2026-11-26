param(
    [Parameter(Mandatory=$true)][string]$Launcher,
    [Parameter(Mandatory=$true)][string]$Game,
    [Parameter(Mandatory=$true)][string]$Mods,
    [switch]$ConfirmOwnedFiles
)
$ErrorActionPreference = 'Stop'
if (-not $ConfirmOwnedFiles) { throw 'Review the ownership registry first; use -ConfirmOwnedFiles to remove only unmodified owned files.' }
$exe = (Resolve-Path -LiteralPath $Launcher).ProviderPath
if ([IO.Path]::GetExtension($exe) -ne '.exe') { throw 'Pass the path to the ModSync EXE.' }
# Both GUI-subsystem builds need an explicit wait before checking the exit code.
& $exe --cli uninstall --game $Game --mods $Mods --confirm-uninstall | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'Uninstall stopped; preserved files and backups.' }
