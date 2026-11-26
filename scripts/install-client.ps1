param(
    [Parameter(Mandatory=$true)][string]$Archive,
    [string]$Destination = (Join-Path $env:LOCALAPPDATA 'Applications\DNTSNE-ModSync-candidate'),
    [string]$ExpectedSha256
)
$ErrorActionPreference = 'Stop'
$archivePath = (Resolve-Path -LiteralPath $Archive).Path
$destinationPath = [IO.Path]::GetFullPath($Destination)
if (Test-Path -LiteralPath $destinationPath) { throw 'Destination already exists; preserve it and choose a new folder.' }
if ($ExpectedSha256 -and (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash -ne $ExpectedSha256) { throw 'Archive checksum mismatch' }
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [IO.Compression.ZipFile]::OpenRead($archivePath)
try {
    $allowedPrefix = $destinationPath.TrimEnd('\') + '\'
    foreach ($entry in $zip.Entries) {
        $resolvedEntry = [IO.Path]::GetFullPath((Join-Path $destinationPath $entry.FullName))
        if (-not $resolvedEntry.StartsWith($allowedPrefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Archive entry escapes destination' }
    }
} finally { $zip.Dispose() }
Expand-Archive -LiteralPath $archivePath -DestinationPath $destinationPath
Write-Output "Portable files installed in $destinationPath. Game and user data were not changed."

