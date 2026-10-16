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
W "motion=dry-run+mock only; this script does not ping the robot or start SSH"
python (Join-Path $PSScriptRoot "detect_host.py") *>&1 | Tee-Object -FilePath $log -Append

W "--- all adapters ---"
Get-NetAdapter | Sort-Object ifIndex |
    Format-Table ifIndex, Name, Status, MacAddress, LinkSpeed, MediaType, InterfaceDescription -AutoSize |
    Out-String | Tee-Object -FilePath $log -Append

W "--- likely physical Ethernet (802.3 / not VMware-Virtual-Hyper-V-Tailscale-ZeroTier-WSL) ---"
$virtualHint = 'VMware|Virtual|Hyper-V|vEthernet|Tailscale|ZeroTier|Bluetooth|Wi-Fi|WLAN|Loopback|WSL|VPN|TAP|TUN'
$eth = Get-NetAdapter | Where-Object {
    $_.MediaType -match '802.3' -and $_.InterfaceDescription -notmatch $virtualHint -and $_.Name -notmatch $virtualHint
}
if (-not $eth) {
    W "No adapter matched the physical-Ethernet heuristic. Inspect the full adapter table above."
} else {
    $eth | Format-Table Name, Status, LinkSpeed, MacAddress, InterfaceDescription -AutoSize | Out-String |
        Tee-Object -FilePath $log -Append
    foreach ($a in $eth) {
        W ("ethernet name={0} status={1} speed={2}" -f $a.Name, $a.Status, $a.LinkSpeed)
    }
}

W "--- IPv4 ---"
Get-NetIPAddress -AddressFamily IPv4 |
    Select-Object InterfaceAlias, IPAddress, PrefixLength, AddressState |
    Format-Table -AutoSize | Out-String | Tee-Object -FilePath $log -Append

W "--- IPv4 route ---"
Get-NetRoute -AddressFamily IPv4 |
    Select-Object InterfaceAlias, DestinationPrefix, NextHop, RouteMetric |
    Format-Table -AutoSize | Out-String | Tee-Object -FilePath $log -Append

W "--- pending (do not guess) ---"
W "1. Which adapter is the cable to the G1 authorized develop port? (unconfirmed)"
W "2. Robot IPv4 is UNVERIFIED. 192.168.123.164 is a candidate only; not pinged."
W "3. SSH user is UNVERIFIED. Do not invent unitree/root."
W "4. After the cable is up and you confirm IP+user, re-run this script, then:"
W "     ssh <authorized-user>@<verified-robot-ip>"
W "     bash scripts/g1/ssh_readonly.sh <authorized-user> <verified-robot-ip>"
W "log=$log"
Write-Host "Wrote $log"
