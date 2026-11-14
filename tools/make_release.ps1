# Build the release zip: the full translation as it goes into the game folder (FEText\, Language\, Speech\).
#
#   pwsh tools\make_release.ps1 -Base D:\path\to\full-pack -Version 1.0.0
#
# -Base is a folder with the complete translation: the previous release zip, extracted. The big files that
# nobody edits (speech, videos, pictures) are not in git and are taken from there. The files of this
# repository (FEText\, Language\) are then copied over them, so what is in git always wins.
# Writes dist\hogs-of-war-ru-<version>.zip and prints its size and SHA-256.
# Run it with PowerShell 7 (pwsh): Windows PowerShell 5.1 writes backslashes into the zip entry names.
[CmdletBinding()] param([Parameter(Mandatory)][string]$Base, [Parameter(Mandatory)][string]$Version)

$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'Run this with PowerShell 7 (pwsh).' }
$root = Split-Path $PSScriptRoot -Parent
$Base = (Resolve-Path -LiteralPath $Base).ProviderPath
$folders = 'FEText', 'Language', 'Speech'
# what the game reads from these folders; anything else in the zip is refused by the installer
$allowed = '.wav', '.bmp', '.bik', '.tab', '.tim', '.bin', '.mad', '.ofs'

foreach ($f in $folders) {
    if (-not (Test-Path -LiteralPath (Join-Path $Base $f))) { throw "$Base has no $f folder: it is not a complete translation" }
}
$dist = Join-Path $root 'dist'
$stage = Join-Path $dist 'stage'
Remove-Item -LiteralPath $dist -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $stage | Out-Null
foreach ($f in $folders) { Copy-Item -LiteralPath (Join-Path $Base $f) -Destination $stage -Recurse }
foreach ($f in 'FEText', 'Language') { Copy-Item -LiteralPath (Join-Path $root $f) -Destination $stage -Recurse -Force }

$all = Get-ChildItem -LiteralPath $stage -Recurse -File
$odd = $all | Where-Object { $allowed -notcontains $_.Extension.ToLowerInvariant() }
if ($odd) { throw "files of a type the game does not read: $(($odd | Select-Object -First 5 -ExpandProperty FullName) -join ', ')" }

$zip = Join-Path $dist "hogs-of-war-ru-$Version.zip"
[IO.Compression.ZipFile]::CreateFromDirectory($stage, $zip, 'Optimal', $false)
Remove-Item -LiteralPath $stage -Recurse -Force
'{0} files, {1:N1} MB unpacked' -f $all.Count, (($all | Measure-Object Length -Sum).Sum / 1MB)
'{0}  {1} bytes' -f $zip, (Get-Item -LiteralPath $zip).Length
'SHA-256 {0}' -f (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash
