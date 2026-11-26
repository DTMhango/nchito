<#
.SYNOPSIS
  Install the Nchito local runner for the current Windows user.

.DESCRIPTION
  Copies the nchito-queue skill to %USERPROFILE%\.claude\skills\nchito-queue, and the MCP
  config, start and check scripts to %USERPROFILE%\.nchito-runner. Checks prerequisites.
  The runner token is kept in a user environment variable, never in a file.

    powershell -NoProfile -ExecutionPolicy Bypass -File runner\local\install.ps1 -Url https://nchito.example.com -SetToken

.PARAMETER Url
  The Nchito instance, for example https://nchito.example.com. Saved as the user variable NCHITO_URL.
.PARAMETER SetToken
  Prompt (hidden input) for the runner token created in Nchito, Settings, Runners, and save
  it as the user variable NCHITO_RUNNER_TOKEN.
.PARAMETER RunnerHome
  Install folder (default %USERPROFILE%\.nchito-runner).
#>
[CmdletBinding()]
param(
    [string]$Url = "",
    [switch]$SetToken,
    [string]$RunnerHome = (Join-Path $env:USERPROFILE ".nchito-runner")
)

$ErrorActionPreference = "Stop"
$src = $PSScriptRoot
$skillDest = Join-Path $env:USERPROFILE ".claude\skills\nchito-queue"

Write-Host "Prerequisites"
$claude = Get-Command claude -ErrorAction SilentlyContinue
if (-not $claude) {
    Write-Error "Claude Code (claude) is not on PATH. Install it first: https://code.claude.com/docs"
}
Write-Host "  claude: $(& claude --version 2>$null | Select-Object -First 1)"

$chromePaths = @(
    (Join-Path ${env:ProgramFiles} "Google\Chrome\Application\chrome.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Google\Chrome\Application\chrome.exe"),
    (Join-Path $env:LOCALAPPDATA "Google\Chrome\Application\chrome.exe")
)
if ($chromePaths | Where-Object { $_ -and (Test-Path $_) }) { Write-Host "  Google Chrome: found" }
else { Write-Warning "Google Chrome not found in the usual places. The runner needs Chrome with the Claude extension." }
Write-Host "  Claude in Chrome extension: cannot be checked from here. Install it from the Chrome Web Store,"
Write-Host "  sign in with the same Claude account as Claude Code, then run /chrome once in Claude Code."

if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) {
    Write-Warning "curl.exe not found; the runner will fall back to Invoke-WebRequest for packet files."
}
foreach ($name in @("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")) {
    if ([Environment]::GetEnvironmentVariable($name, "User") -or [Environment]::GetEnvironmentVariable($name, "Machine")) {
        Write-Warning "$name is set permanently. Claude Code keeps Chrome off with it; start.ps1 drops it for runner sessions."
    }
}

Write-Host "Settings"
if ($Url) {
    $Url = $Url.TrimEnd("/")
    if ($Url -notmatch '^https?://[^/\s]+') { Write-Error "-Url must look like https://nchito.example.com" }
    [Environment]::SetEnvironmentVariable("NCHITO_URL", $Url, "User")
    $env:NCHITO_URL = $Url
    Write-Host "  NCHITO_URL saved for this Windows user."
} elseif (-not [Environment]::GetEnvironmentVariable("NCHITO_URL", "User")) {
    Write-Warning "NCHITO_URL is not set. Re-run with -Url https://<your instance>."
}
if ($SetToken) {
    $secure = Read-Host -AsSecureString "Runner token (nch_..., from Settings, Runners)"
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
    if ($plain -notmatch '^nch_\S+$') { Write-Error "That does not look like a runner token (nch_...). Nothing saved." }
    [Environment]::SetEnvironmentVariable("NCHITO_RUNNER_TOKEN", $plain, "User")
    $env:NCHITO_RUNNER_TOKEN = $plain
    $plain = $null
    Write-Host "  NCHITO_RUNNER_TOKEN saved as a user environment variable (not in any file)."
} elseif (-not [Environment]::GetEnvironmentVariable("NCHITO_RUNNER_TOKEN", "User")) {
    Write-Warning "NCHITO_RUNNER_TOKEN is not set. Re-run with -SetToken."
}

Write-Host "Files"
New-Item -ItemType Directory -Force -Path $skillDest, $RunnerHome, (Join-Path $RunnerHome "work"), (Join-Path $RunnerHome "logs") | Out-Null
if (Test-Path (Join-Path $skillDest "reference")) { Remove-Item -Recurse -Force (Join-Path $skillDest "reference") }
Copy-Item -Recurse -Force -Path (Join-Path $src "skills\nchito-queue\*") -Destination $skillDest
Write-Host "  skill -> $skillDest"

Copy-Item -Force (Join-Path $src "mcp.template.json") (Join-Path $RunnerHome "mcp.json")
foreach ($f in @("start.ps1", "check.ps1", "start.sh", "check.sh")) {
    Copy-Item -Force (Join-Path $src $f) (Join-Path $RunnerHome $f)
}
New-Item -ItemType Directory -Force -Path (Join-Path $RunnerHome "scheduled") | Out-Null
Copy-Item -Force (Join-Path $src "scheduled\*") (Join-Path $RunnerHome "scheduled")
Write-Host "  config and scripts -> $RunnerHome"

Write-Host "Self-check"
& (Join-Path $RunnerHome "check.ps1")
$ok = ($LASTEXITCODE -eq 0)

Write-Host ""
Write-Host "Start the runner (one line, any new terminal):"
Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File `"$RunnerHome\start.ps1`""
Write-Host "First time, a dry run (reads one form, enters nothing):"
Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File `"$RunnerHome\start.ps1`" -Arguments dry-run"
Write-Host "Open a new terminal first so it sees the saved environment variables."
if (-not $ok) { exit 1 }
