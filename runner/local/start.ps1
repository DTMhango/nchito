<#
.SYNOPSIS
  Start Claude Code with Chrome and the Nchito gateway, and work the queue.

.DESCRIPTION
  Installed by install.ps1 into %USERPROFILE%\.nchito-runner. One-line start:

    powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\.nchito-runner\start.ps1"

  Reads NCHITO_URL and NCHITO_RUNNER_TOKEN from the environment; the token is never written
  to a file. Runs in %USERPROFILE%\.nchito-runner\work, where packet files and screenshots go.

.PARAMETER Arguments
  Passed to the skill: "dry-run", "max=5", "kinds=apply" (combine with spaces).
.PARAMETER Loop
  Interval for a long-lived /loop session, for example "30m" or "1h". Empty: work the queue once.
.PARAMETER Print
  Headless one-shot run (claude -p). Chrome in print mode is undocumented: see UNATTENDED.md.
.PARAMETER Unattended
  No permission prompts: tools outside the allow list are denied (permission mode dontAsk),
  the self-check runs first and output is logged under logs\.
.PARAMETER MaxTurns
  Print mode only: cap on agent turns (0 = no cap passed).
#>
[CmdletBinding()]
param(
    [string]$Arguments = "",
    [string]$Loop = "",
    [switch]$Print,
    [switch]$Unattended,
    [int]$MaxTurns = 0
)

$ErrorActionPreference = "Stop"
$RunnerHome = $PSScriptRoot
$McpConfig = Join-Path $RunnerHome "mcp.json"
$Work = Join-Path $RunnerHome "work"
$Logs = Join-Path $RunnerHome "logs"

foreach ($name in @("NCHITO_URL", "NCHITO_RUNNER_TOKEN")) {
    if (-not [Environment]::GetEnvironmentVariable($name)) {
        Write-Error "$name is not set. Run install.ps1 (or set it as a user environment variable) first."
    }
}
if (-not (Test-Path $McpConfig)) { Write-Error "Missing $McpConfig. Run install.ps1 first." }
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) { Write-Error "claude is not on PATH." }

# Chrome integration is switched off when Claude Code authenticates with an API key or a
# setup-token. Drop them for this process only, so the subscription login is used.
foreach ($name in @("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")) {
    if ([Environment]::GetEnvironmentVariable($name)) {
        Write-Warning "$name is set; ignoring it for this run (Chrome needs the subscription login)."
        Remove-Item "Env:$name"
    }
}

if ($Loop -and $Print) { Write-Error "-Loop and -Print cannot be combined." }
if ($Loop -and $Loop -notmatch '^\d+[smhd]$') { Write-Error "-Loop must look like 30m, 1h or 1d." }

New-Item -ItemType Directory -Force -Path $Work, $Logs | Out-Null

if ($Unattended) {
    & (Join-Path $RunnerHome "check.ps1") -Quiet
    if ($LASTEXITCODE -ne 0) { Write-Error "Self-check failed; not starting." }
}

$skill = ("/nchito-queue " + $Arguments).Trim()
$prompt = if ($Loop) { "/loop $Loop $skill" } else { $skill }

# Least privilege: the gateway, the browser, downloading and hashing packet files. No page
# scripting, no file edits, no web fetches outside the browser.
$allowed = @(
    "mcp__nchito__*",
    "mcp__claude-in-chrome__*",
    "Bash(curl *)", "Bash(sha256sum *)", "Bash(mkdir *)", "Bash(rm -rf files/*)",
    "PowerShell(Invoke-WebRequest *)", "PowerShell(Get-FileHash *)", "PowerShell(New-Item *)", "PowerShell(Remove-Item -Recurse -Force files*)",
    "Read"
)
$denied = @("mcp__claude-in-chrome__javascript_tool", "Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch")

# The prompt goes first: --allowedTools and --disallowedTools take every following value.
$cliArgs = @()
if ($Print) { $cliArgs += "-p" }
$cliArgs += $prompt
$cliArgs += @("--chrome", "--mcp-config", $McpConfig)
if ($Unattended) { $cliArgs += @("--permission-mode", "dontAsk") }
if ($Print -and $MaxTurns -gt 0) { $cliArgs += @("--max-turns", "$MaxTurns") }
if ($Print) { $cliArgs += @("--output-format", "json") }
$cliArgs += "--allowedTools"; $cliArgs += $allowed
$cliArgs += "--disallowedTools"; $cliArgs += $denied

# Packet files (CVs, letters) are downloaded to work\files\<task>; they never outlive a session.
$PacketFiles = Join-Path $Work "files"
function Clear-PacketFiles { if (Test-Path $PacketFiles) { Remove-Item -Recurse -Force $PacketFiles } }

Set-Location $Work
Clear-PacketFiles
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
if ($Print) {
    $log = Join-Path $Logs "run-$stamp.json"
    try { & claude @cliArgs | Out-File -Encoding utf8 -FilePath $log; $code = $LASTEXITCODE }
    finally { Clear-PacketFiles }
    Write-Host "claude -p exited $code; output in $log"
    exit $code
}
if ($Unattended) { Start-Transcript -Path (Join-Path $Logs "session-$stamp.txt") | Out-Null }
try { & claude @cliArgs }
finally {
    Clear-PacketFiles
    if ($Unattended) { Stop-Transcript | Out-Null }
}
