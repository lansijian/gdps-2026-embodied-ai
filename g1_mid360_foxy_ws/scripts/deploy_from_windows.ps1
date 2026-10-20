param(
  [Parameter(Mandatory=$true)][string]$RobotHost,
  [string]$RobotUser = 'unitree',
  [string]$Destination = '/home/unitree/g1_mid360_foxy_ws',
  [string]$Source = (Split-Path $PSScriptRoot -Parent)
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($RobotHost -notmatch '^[a-zA-Z0-9][a-zA-Z0-9.:-]*$' -or $RobotUser -notmatch '^[a-z_][a-z0-9_-]*$') { throw 'Invalid SSH host/user' }
if ($Destination -notmatch '^/home/[a-zA-Z0-9_-]+/[a-zA-Z0-9_/-]+$' -or $Destination.Contains('..')) { throw 'Use an explicit safe directory under /home/<user>/' }
$Source = (Resolve-Path -LiteralPath $Source).Path
$archive = Join-Path $env:TEMP ('g1-mid360-' + [guid]::NewGuid().ToString('N') + '.tar.gz')
& python (Join-Path $PSScriptRoot 'package_workspace.py') --source $Source --output $archive
if ($LASTEXITCODE -ne 0) { throw 'Packaging failed' }
$hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
$remoteArchive = '/tmp/' + (Split-Path $archive -Leaf)
$login = "$RobotUser@$RobotHost"
# SSH validates the actual host key using the user's normal OpenSSH configuration.
& scp $archive "${login}:$remoteArchive"
if ($LASTEXITCODE -ne 0) { throw 'Copy failed' }
& ssh $login "set -eu; test ! -e '$Destination'; echo '$hash  $remoteArchive' | sha256sum -c -; mkdir '$Destination'; tar -xzf '$remoteArchive' -C '$Destination'; echo 'COPY_COMPLETE LIVE_DISABLED'"
if ($LASTEXITCODE -ne 0) { throw 'Deploy failed; existing destination is never overwritten. Select a new release directory.' }
Write-Output "Copied with SHA256 $hash. Run bash $Destination/scripts/install_dependencies.sh --plan, review, then --install; bash $Destination/scripts/build_on_g1.sh. No services or motion started."
Write-Output "Rollback: stop this release with Ctrl-C and return to the previous directory; no factory services are changed. Local archive retained: $archive"
