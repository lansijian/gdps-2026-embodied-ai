# Package read-only field diagnostics (review before scp to G1)
$Root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$OutDir = Join-Path $Root "dist"
$Stamp = Get-Date -Format "yyyyMMdd"
$Zip = Join-Path $OutDir "gdps-qi-field-diag-$Stamp.zip"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$Stage = Join-Path $env:TEMP "gdps-qi-field-diag-stage"
if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
New-Item -ItemType Directory -Force -Path $Stage | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Stage "scripts\g1") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Stage "tracks\quality-inspection") | Out-Null
Copy-Item -Recurse (Join-Path $Root "scripts\g1\qi_hardware_diagnostics.py") (Join-Path $Stage "scripts\g1\") -Force
Copy-Item -Recurse (Join-Path $Root "scripts\g1\field_diag_bundle") (Join-Path $Stage "scripts\g1\") -Force
Copy-Item -Recurse (Join-Path $Root "tracks\quality-inspection\gdps_qi") (Join-Path $Stage "tracks\quality-inspection\") -Force
Copy-Item -Recurse (Join-Path $Root "tracks\quality-inspection\configs") (Join-Path $Stage "tracks\quality-inspection\") -Force
if (Test-Path $Zip) { Remove-Item $Zip }
Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $Zip
Write-Host "Created $Zip"
