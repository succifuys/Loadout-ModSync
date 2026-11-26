param([Parameter(Mandatory=$true)][string]$Game, [Parameter(Mandatory=$true)][string]$Mods, [switch]$ConfirmOwnedFiles)
$ErrorActionPreference = 'Stop'
if (-not $ConfirmOwnedFiles) { throw 'Review the ownership registry first; use -ConfirmOwnedFiles to remove only unmodified owned files.' }
$projectRoot = Split-Path -Parent $PSScriptRoot
& "$projectRoot\dist\DNTSNE-ModSync\DNTSNE-ModSync.exe" --cli uninstall --game $Game --mods $Mods --confirm-uninstall
if ($LASTEXITCODE -ne 0) { throw 'Uninstall stopped; preserved files and backups.' }

