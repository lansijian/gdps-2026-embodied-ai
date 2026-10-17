param([string]$Out = "")
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $Out) { $Out = Join-Path $Root "dist/gdps-s05-phase441-readonly.zip" }
python (Join-Path $PSScriptRoot "package_phase44.py") --out $Out
if ($LASTEXITCODE -ne 0) { throw "Packaging failed" }
Get-FileHash -LiteralPath $Out -Algorithm SHA256
