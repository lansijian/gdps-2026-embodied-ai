# Read-only network / host preflight for G1 EDU. Does not change IP or SSH.
param(
    [string]$LogDir = ""
)
$ErrorActionPreference = "Continue"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
if (-not $LogDir) {
    $LogDir = Join-Path $RepoRoot "logs\g1-preflight"
}
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$log = Join-Path $LogDir "preflight-$stamp.txt"
function W($msg) {
    $line = "$(Get-Date -Format o) $msg"
    $line | Tee-Object -FilePath $log -Append
}
W "GDPS G1 preflight (Windows PowerShell, read-only)"
W "repo=$RepoRoot"
W "os=$([System.Environment]::OSVersion.VersionString)"
python (Join-Path $PSScriptRoot "detect_host.py") *>&1 | Tee-Object -FilePath $log -Append
W "--- adapters ---"
Get-NetAdapter | Format-Table Name, Status, MacAddress, LinkSpeed -AutoSize | Out-String | Tee-Object -FilePath $log -Append
W "--- IPv4 ---"
Get-NetIPAddress -AddressFamily IPv4 | Select-Object InterfaceAlias, IPAddress, PrefixLength | Format-Table -AutoSize | Out-String | Tee-Object -FilePath $log -Append
W "--- IPv4 route ---"
Get-NetRoute -AddressFamily IPv4 | Select-Object InterfaceAlias, DestinationPrefix, NextHop, RouteMetric | Format-Table -AutoSize | Out-String | Tee-Object -FilePath $log -Append
W "Candidate robot IP 192.168.123.164 is UNVERIFIED. Not pinging unless you pass it later."
W "Do not guess SSH user. After you confirm IP/user, run:"
W "  ssh <authorized-user>@<verified-robot-ip>"
W "log=$log"
Write-Host "Wrote $log"
