#!/usr/bin/env bash
# Start Claude Code with Chrome and the Nchito gateway, and work the queue.
#
#   ~/.nchito-runner/start.sh [skill arguments]          # e.g. dry-run, max=5
#   NCHITO_LOOP=30m ~/.nchito-runner/start.sh             # long-lived /loop session
#   NCHITO_PRINT=1 ~/.nchito-runner/start.sh max=5        # headless one-shot (claude -p)
#   NCHITO_UNATTENDED=1 ...                               # no prompts (dontAsk), self-check first
#
# Reads NCHITO_URL and NCHITO_RUNNER_TOKEN from the environment; the token is never written
# to a file. Runs in ~/.nchito-runner/work, where packet files and screenshots go.
set -euo pipefail

runner_home="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mcp_config="$runner_home/mcp.json"
work="$runner_home/work"
logs="$runner_home/logs"
loop="${NCHITO_LOOP:-}"
print="${NCHITO_PRINT:-}"
unattended="${NCHITO_UNATTENDED:-}"
max_turns="${NCHITO_MAX_TURNS:-}"

for name in NCHITO_URL NCHITO_RUNNER_TOKEN; do
  if [ -z "${!name:-}" ]; then echo "$name is not set." >&2; exit 1; fi
done
[ -f "$mcp_config" ] || { echo "Missing $mcp_config. Run install.sh first." >&2; exit 1; }
command -v claude >/dev/null 2>&1 || { echo "claude is not on PATH." >&2; exit 1; }
if [ -n "$loop" ] && [ -n "$print" ]; then echo "NCHITO_LOOP and NCHITO_PRINT cannot be combined." >&2; exit 1; fi
if [ -n "$loop" ] && ! [[ "$loop" =~ ^[0-9]+[smhd]$ ]]; then echo "NCHITO_LOOP must look like 30m, 1h or 1d." >&2; exit 1; fi

# Chrome integration is off when Claude Code authenticates with an API key or setup-token.
for name in ANTHROPIC_API_KEY CLAUDE_CODE_OAUTH_TOKEN; do
  if [ -n "${!name:-}" ]; then
    echo "warn: $name is set; ignoring it for this run (Chrome needs the subscription login)." >&2
    unset "$name"
  fi
done

mkdir -p "$work" "$logs"
if [ -n "$unattended" ]; then
  "$runner_home/check.sh" --quiet || { echo "Self-check failed; not starting." >&2; exit 1; }
fi

skill="/nchito-queue${*:+ $*}"
if [ -n "$loop" ]; then prompt="/loop $loop $skill"; else prompt="$skill"; fi

args=()
[ -n "$print" ] && args+=(-p)
args+=("$prompt" --chrome --mcp-config "$mcp_config")
[ -n "$unattended" ] && args+=(--permission-mode dontAsk)
[ -n "$print" ] && [ -n "$max_turns" ] && args+=(--max-turns "$max_turns")
[ -n "$print" ] && args+=(--output-format json)
args+=(--allowedTools "mcp__nchito__*" "mcp__claude-in-chrome__*"
  "Bash(curl *)" "Bash(sha256sum *)" "Bash(mkdir *)" "Bash(rm -rf files/*)"
  "PowerShell(Invoke-WebRequest *)" "PowerShell(Get-FileHash *)" "PowerShell(New-Item *)" "PowerShell(Remove-Item -Recurse -Force files*)" "Read")
args+=(--disallowedTools "mcp__claude-in-chrome__javascript_tool" Edit Write NotebookEdit WebFetch WebSearch)

cd "$work"
# Packet files (CVs, letters) never outlive a session.
rm -rf "$work/files"
trap 'rm -rf "$work/files"' EXIT
if [ -n "$print" ]; then
  log="$logs/run-$(date +%Y%m%d-%H%M%S).json"
  status=0
  claude "${args[@]}" >"$log" || status=$?
  echo "claude -p exited $status; output in $log"
  exit "$status"
fi
claude "${args[@]}"
