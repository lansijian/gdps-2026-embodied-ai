# Package read-only field diagnostics (whitelist; review before scp to G1)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$OutDir = Join-Path $Root "dist"
$Stamp = Get-Date -Format "yyyyMMdd"
$ZipName = "gdps-qi-field-diag-$Stamp.zip"
$Zip = Join-Path $OutDir $ZipName
$Commit = ""
try {
    $Commit = (git -C $Root rev-parse HEAD 2>$null)
} catch { $Commit = "unknown" }

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$Stage = Join-Path $env:TEMP "gdps-qi-field-diag-stage"
if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
New-Item -ItemType Directory -Force -Path $Stage | Out-Null

$Whitelist = @(
    "scripts/g1/qi_hardware_diagnostics.py",
    "scripts/g1/field_diag_bundle/README_DEPLOY.md",
    "scripts/g1/field_diag_bundle/package_field_diag.ps1",
    "tracks/quality-inspection/gdps_qi",
    "tracks/quality-inspection/configs/g1/qi_topics_readonly.example.yaml"
)

$ExcludePattern = '(\\__pycache__|\\\.env|\.pyc$|\.log$|\.git\\|credentials|secret|token)'

$ManifestLines = @()
foreach ($rel in $Whitelist) {
    $src = Join-Path $Root ($rel -replace '/', '\')
    if (-not (Test-Path $src)) {
        throw "Missing whitelist path: $rel"
    }
    $dest = Join-Path $Stage ($rel -replace '/', '\')
    if (Test-Path $src -PathType Container) {
        $destParent = Split-Path -Parent $dest
        New-Item -ItemType Directory -Force -Path $destParent | Out-Null
        Get-ChildItem -Path $src -Recurse -File | Where-Object { $_.FullName -notmatch $ExcludePattern } | ForEach-Object {
            $relFile = $_.FullName.Substring($Root.Length + 1)
            $target = Join-Path $Stage $relFile
            $targetDir = Split-Path -Parent $target
            New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
            Copy-Item $_.FullName $target -Force
            $hash = (Get-FileHash -Path $target -Algorithm SHA256).Hash.ToLower()
            $ManifestLines += "$hash  $relFile"
        }
    } else {
        $destDir = Split-Path -Parent $dest
        New-Item -ItemType Directory -Force -Path $destDir | Out-Null
        Copy-Item $src $dest -Force
        $hash = (Get-FileHash -Path $dest -Algorithm SHA256).Hash.ToLower()
        $ManifestLines += "$hash  $rel"
    }
}

$ManifestPath = Join-Path $Stage "MANIFEST.sha256"
$Header = @(
    "# GDPS QI field diagnostics bundle",
    "generated_utc=$(Get-Date -Format o)",
    "source_commit=$Commit",
    "zip_name=$ZipName",
    ""
)
($Header + ($ManifestLines | Sort-Object)) | Set-Content -Path $ManifestPath -Encoding UTF8
$ManifestLines += ((Get-FileHash -Path $ManifestPath -Algorithm SHA256).Hash.ToLower() + "  MANIFEST.sha256")

if (Test-Path $Zip) { Remove-Item $Zip -Force }
Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $Zip
$ZipHash = (Get-FileHash -Path $Zip -Algorithm SHA256).Hash.ToLower()
$SummaryPath = Join-Path $OutDir "gdps-qi-field-diag-$Stamp.summary.txt"
@"
zip_file=$ZipName
zip_sha256=$ZipHash
source_commit=$Commit
file_count=$($ManifestLines.Count)
"@ | Set-Content -Path $SummaryPath -Encoding UTF8
Write-Host "Created $Zip"
Write-Host "SHA256 $ZipHash"
Write-Host "Commit $Commit"
Write-Host "Summary $SummaryPath"
