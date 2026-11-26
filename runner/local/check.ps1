<#
.SYNOPSIS
  Self-check for the Nchito local runner. Needs no browser.

.DESCRIPTION
  Checks: environment variables, the installed MCP config (placeholders only, no token in the
  file), the skill, the claude CLI, conflicting auth variables, GET /api/health/live, and the
  gateway itself with the runner token: MCP initialize, tools/list compared with the tools this
  kit expects, and get_runner_config (is this runner switched on). Exit code 0 when nothing failed.

.PARAMETER RunnerHome
  Install folder (default: this script's folder).
.PARAMETER Quiet
  Print only warnings and failures.
#>
[CmdletBinding()]
param(
    [string]$RunnerHome = $PSScriptRoot,
    [switch]$Quiet
)

$script:failed = 0
function Write-Ok([string]$m) { if (-not $Quiet) { Write-Host "  ok    $m" } }
function Write-Warn([string]$m) { Write-Host "  warn  $m" -ForegroundColor Yellow }
function Write-Fail([string]$m) { Write-Host "  FAIL  $m" -ForegroundColor Red; $script:failed++ }

function Get-HttpStatus([string]$Method, [string]$Uri, [hashtable]$Headers, [string]$Body) {
    # Returns @{ Status = <int or 0>; Body = <string>; Error = <string> } without throwing.
    $p = @{ Method = $Method; Uri = $Uri; UseBasicParsing = $true; MaximumRedirection = 0; TimeoutSec = 15 }
    if ($Headers) { $p.Headers = $Headers }
    if ($Body) { $p.Body = $Body; $p.ContentType = "application/json" }
    try {
        $r = Invoke-WebRequest @p -ErrorAction Stop
        return @{ Status = [int]$r.StatusCode; Body = [string]$r.Content; Error = "" }
    } catch {
        $resp = $_.Exception.Response
        if ($resp) { return @{ Status = [int]$resp.StatusCode; Body = ""; Error = $_.Exception.Message } }
        return @{ Status = 0; Body = ""; Error = $_.Exception.Message }
    }
}

# The gateway tools this kit is written for (backend/app/gateway/tools.py; nchito_runner.gateway.EXPECTED_TOOLS).
$ExpectedTools = @("next_task", "get_packet", "find_answer", "save_checkpoint", "raise_blocker", "request_submit_permit",
    "report_result", "report_jobs", "report_check", "release_task", "evidence_upload_url", "get_runner_config")

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.ServicePointManager]::SecurityProtocol

if (-not $Quiet) { Write-Host "Nchito runner self-check ($RunnerHome)" }

# 1. Environment
$url = [Environment]::GetEnvironmentVariable("NCHITO_URL")
$token = [Environment]::GetEnvironmentVariable("NCHITO_RUNNER_TOKEN")
if (-not $url) { Write-Fail "NCHITO_URL is not set" }
elseif ($url -notmatch '^https?://[^/\s]+(:\d+)?(/[^\s]*)?$' -or $url.EndsWith("/")) {
    Write-Fail "NCHITO_URL must look like https://nchito.example.com (no trailing slash)"
} else {
    if ($url -match '^http://' -and $url -notmatch '^http://(localhost|127\.0\.0\.1)(:|/|$)') {
        Write-Warn "NCHITO_URL is plain http on a non-local host; the token would travel unencrypted"
    }
    Write-Ok "NCHITO_URL = $url"
}
if (-not $token) { Write-Fail "NCHITO_RUNNER_TOKEN is not set" }
elseif ($token -notmatch '^nch_\S+$') { Write-Fail "NCHITO_RUNNER_TOKEN does not look like a runner token (nch_...)" }
else { Write-Ok "NCHITO_RUNNER_TOKEN is set (nch_..., $($token.Length) chars)" }

foreach ($name in @("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")) {
    if ([Environment]::GetEnvironmentVariable($name)) {
        Write-Warn "$name is set: Claude Code turns Chrome off with it. start.ps1 drops it for its own runs."
    }
}

# 2. MCP config
$mcp = Join-Path $RunnerHome "mcp.json"
if (-not (Test-Path $mcp)) { Write-Fail "missing $mcp (run install.ps1)" }
else {
    $raw = Get-Content -Raw -Path $mcp
    try {
        $cfg = $raw | ConvertFrom-Json -ErrorAction Stop
        $srv = $cfg.mcpServers.nchito
        if (-not $srv) { Write-Fail "mcp.json has no mcpServers.nchito" }
        else {
            if ($srv.type -ne "http") { Write-Fail "mcpServers.nchito.type must be http" }
            if ($srv.url -ne '${NCHITO_URL}/mcp') { Write-Warn "mcpServers.nchito.url is '$($srv.url)', expected `${NCHITO_URL}/mcp" }
            if ($srv.headers.Authorization -ne 'Bearer ${NCHITO_RUNNER_TOKEN}') {
                Write-Fail "Authorization header must be the placeholder 'Bearer `${NCHITO_RUNNER_TOKEN}'"
            }
        }
        if ($raw -match 'nch_[A-Za-z0-9]') { Write-Fail "mcp.json contains a literal token; replace it with `${NCHITO_RUNNER_TOKEN}" }
        else { Write-Ok "mcp.json valid, token by placeholder only" }
    } catch { Write-Fail "mcp.json is not valid JSON: $($_.Exception.Message)" }
}

# 3. Skill and CLI
$skill = Join-Path $env:USERPROFILE ".claude\skills\nchito-queue\SKILL.md"
if (Test-Path $skill) { Write-Ok "skill installed" } else { Write-Fail "skill missing at $skill (run install.ps1)" }
$claude = Get-Command claude -ErrorAction SilentlyContinue
if (-not $claude) { Write-Fail "claude is not on PATH" }
else {
    $ver = (& claude --version 2>$null | Select-Object -First 1)
    Write-Ok "claude $ver"
}

# 4. Server
if ($url) {
    $live = Get-HttpStatus -Method GET -Uri "$url/api/health/live"
    if ($live.Status -eq 200) { Write-Ok "GET /api/health/live -> 200" }
    else { Write-Fail "GET /api/health/live -> $($live.Status) $($live.Error)" }

    if ($token) {
        $h = @{ Authorization = "Bearer $token"; Accept = "application/json, text/event-stream" }
        $init = '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"nchito-runner-check","version":"1"}}}'
        $m = Get-HttpStatus -Method POST -Uri "$url/mcp" -Headers $h -Body $init
        $gatewayUp = $false
        switch ($m.Status) {
            200 {
                if ($m.Body -match 'serverInfo') { Write-Ok "POST /mcp initialize -> 200, token accepted"; $gatewayUp = $true }
                else { Write-Fail "POST /mcp -> 200 but no serverInfo in the reply" }
            }
            401 { Write-Fail "POST /mcp -> 401: token rejected (unknown, revoked or mistyped)" }
            429 { Write-Warn "POST /mcp -> 429: too many calls from this token; try again in a minute" }
            { $_ -in 307, 308 } { Write-Fail "POST /mcp -> $($m.Status) redirect: check NCHITO_URL (scheme, host, no path)" }
            default { Write-Fail "POST /mcp -> $($m.Status) $($m.Error)" }
        }
        if ($gatewayUp) {
            # The gateway is stateless: each request stands alone. Compare its tools with this kit's.
            $list = Get-HttpStatus -Method POST -Uri "$url/mcp" -Headers $h -Body '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
            $names = @()
            try { $names = @(($list.Body | ConvertFrom-Json).result.tools | ForEach-Object { $_.name }) } catch { }
            if ($list.Status -ne 200 -or $names.Count -eq 0) { Write-Fail "tools/list -> $($list.Status): no tool list from the gateway" }
            else {
                $missing = @($ExpectedTools | Where-Object { $names -notcontains $_ })
                $extra = @($names | Where-Object { $ExpectedTools -notcontains $_ })
                if ($missing.Count -gt 0) { Write-Fail "the gateway lacks $($missing -join ', '): update Nchito or this runner kit" }
                else { Write-Ok "tools/list: all $($ExpectedTools.Count) expected gateway tools present" }
                if ($extra.Count -gt 0) { Write-Warn "the gateway has tools this kit does not know: $($extra -join ', ') (update the kit)" }
            }
            $call = '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_runner_config","arguments":{}}}'
            $rc = Get-HttpStatus -Method POST -Uri "$url/mcp" -Headers $h -Body $call
            try {
                $res = ($rc.Body | ConvertFrom-Json).result
                $conf = $res.structuredContent
                if ($res.isError -or -not $conf) { Write-Fail "get_runner_config refused: $($res.content[0].text)" }
                elseif (-not $conf.enabled) { Write-Fail "this runner ($($conf.runner_kind)) is switched off or suspended: see Settings, Runners" }
                else { Write-Ok "get_runner_config: $($conf.runner_kind) runner enabled, $($conf.max_steps) steps per task" }
            } catch { Write-Fail "get_runner_config -> $($rc.Status): unreadable reply" }
        }
    }
}

if ($script:failed -gt 0) { Write-Host "$($script:failed) check(s) failed." -ForegroundColor Red; exit 1 }
if (-not $Quiet) { Write-Host "All checks passed (warnings above, if any, need a look)." }
exit 0
