<#
.SYNOPSIS
  Register (or remove) the "Nchito runner" Windows scheduled task for the current user.

.DESCRIPTION
  Fills nchito-runner.task.xml with this user, the install folder and the loop interval, and
  registers it under \Nchito\. The task runs only while this user is signed in (it needs the
  desktop for Chrome), starts two minutes after sign-in and again each morning at 07:00 if the
  session has stopped, and never runs two copies.

    powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\.nchito-runner\scheduled\register-task.ps1"
    ... register-task.ps1 -Interval 1h
    ... register-task.ps1 -Remove

.PARAMETER Interval
  /loop interval, for example 30m or 1h.
.PARAMETER RunnerHome
  Install folder (default: the parent of this script's folder).
.PARAMETER Remove
  Unregister the task instead.
#>
[CmdletBinding()]
param(
    [string]$Interval = "30m",
    [string]$RunnerHome = (Split-Path -Parent $PSScriptRoot),
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$taskName = "Nchito runner"
$taskPath = "\Nchito\"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $taskName -TaskPath $taskPath -Confirm:$false
    Write-Host "Removed $taskPath$taskName."
    return
}
if ($Interval -notmatch '^\d+[mhd]$') { Write-Error "-Interval must look like 30m, 1h or 1d." }
if (-not (Test-Path (Join-Path $RunnerHome "start.ps1"))) { Write-Error "No start.ps1 in $RunnerHome; run install.ps1 first." }

$user = "$env:USERDOMAIN\$env:USERNAME"
$xml = Get-Content -Raw -Path (Join-Path $PSScriptRoot "nchito-runner.task.xml")
$xml = $xml.Replace("__USER__", [Security.SecurityElement]::Escape($user))
$xml = $xml.Replace("__RUNNER_HOME__", [Security.SecurityElement]::Escape($RunnerHome))
$xml = $xml.Replace("__INTERVAL__", $Interval)
[xml]$null = $xml   # fail early on a malformed result

Register-ScheduledTask -Xml $xml -TaskName $taskName -TaskPath $taskPath -Force | Out-Null
Write-Host "Registered $taskPath$taskName for $user (loop every $Interval)."
Write-Host "Start it now:  Start-ScheduledTask -TaskPath '$taskPath' -TaskName '$taskName'"
Write-Host "Remove it:     register-task.ps1 -Remove"
