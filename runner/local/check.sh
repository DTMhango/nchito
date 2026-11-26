#!/usr/bin/env bash
# Self-check for the Nchito local runner. Needs no browser.
#   check.sh [--quiet]
# Checks environment variables, the installed MCP config (placeholders only), the skill, the
# claude CLI, GET /api/health/live, and the gateway with the runner token: MCP initialize,
# tools/list compared with the tools this kit expects, and get_runner_config (is this runner
# switched on). Exit 0 when nothing failed.
set -uo pipefail

runner_home="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
quiet=""
[ "${1:-}" = "--quiet" ] && quiet=1
failed=0
ok()   { [ -n "$quiet" ] || echo "  ok    $1"; }
warn() { echo "  warn  $1"; }
fail() { echo "  FAIL  $1"; failed=$((failed + 1)); }

[ -n "$quiet" ] || echo "Nchito runner self-check ($runner_home)"

# The gateway tools this kit is written for (backend/app/gateway/tools.py; nchito_runner.gateway.EXPECTED_TOOLS).
expected_tools="next_task get_packet find_answer save_checkpoint raise_blocker request_submit_permit report_result report_jobs report_check release_task evidence_upload_url get_runner_config"

url="${NCHITO_URL:-}"
token="${NCHITO_RUNNER_TOKEN:-}"
if [ -z "$url" ]; then fail "NCHITO_URL is not set"
elif ! [[ "$url" =~ ^https?://[^/[:space:]]+(/[^[:space:]]*)?$ ]] || [[ "$url" == */ ]]; then
  fail "NCHITO_URL must look like https://nchito.example.com (no trailing slash)"
else
  if [[ "$url" =~ ^http:// ]] && ! [[ "$url" =~ ^http://(localhost|127\.0\.0\.1)(:|/|$) ]]; then
    warn "NCHITO_URL is plain http on a non-local host; the token would travel unencrypted"
  fi
  ok "NCHITO_URL = $url"
fi
if [ -z "$token" ]; then fail "NCHITO_RUNNER_TOKEN is not set"
elif ! [[ "$token" =~ ^nch_[^[:space:]]+$ ]]; then fail "NCHITO_RUNNER_TOKEN does not look like a runner token (nch_...)"
else ok "NCHITO_RUNNER_TOKEN is set (nch_..., ${#token} chars)"
fi
for name in ANTHROPIC_API_KEY CLAUDE_CODE_OAUTH_TOKEN; do
  [ -z "${!name:-}" ] || warn "$name is set: Claude Code turns Chrome off with it. start.sh drops it for its own runs."
done

mcp="$runner_home/mcp.json"
if [ ! -f "$mcp" ]; then fail "missing $mcp (run install.sh)"
else
  py=""
  for c in python3 python; do command -v "$c" >/dev/null 2>&1 && { py="$c"; break; }; done
  if [ -n "$py" ]; then
    if msg="$("$py" -c '
import json, sys
cfg = json.load(open(sys.argv[1], encoding="utf-8"))
s = cfg.get("mcpServers", {}).get("nchito")
if not s: sys.exit("mcp.json has no mcpServers.nchito")
if s.get("type") != "http": sys.exit("mcpServers.nchito.type must be http")
if s.get("headers", {}).get("Authorization") != "Bearer ${NCHITO_RUNNER_TOKEN}":
    sys.exit("Authorization header must be the placeholder Bearer ${NCHITO_RUNNER_TOKEN}")
' "$mcp" 2>&1)"; then ok "mcp.json valid"; else fail "${msg:-mcp.json is not valid JSON}"; fi
  else
    warn "no python found; mcp.json structure not checked"
  fi
  if grep -Eq 'nch_[A-Za-z0-9]' "$mcp"; then fail "mcp.json contains a literal token; use \${NCHITO_RUNNER_TOKEN}"; fi
fi

if [ -f "$HOME/.claude/skills/nchito-queue/SKILL.md" ]; then ok "skill installed"
else fail "skill missing at ~/.claude/skills/nchito-queue (run install.sh)"; fi
if command -v claude >/dev/null 2>&1; then ok "claude $(claude --version 2>/dev/null | head -n 1)"
else fail "claude is not on PATH"; fi

if [ -n "$url" ]; then
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$url/api/health/live" || true)"
  if [ "$code" = "200" ]; then ok "GET /api/health/live -> 200"; else fail "GET /api/health/live -> ${code:-no answer}"; fi

  if [ -n "$token" ]; then
    body_file="$(mktemp)"
    # One stateless MCP request; the token goes in a header read from stdin, so it does not
    # appear in the process list. Prints the HTTP status; the reply lands in $body_file.
    mcp_post() {
      printf 'Authorization: Bearer %s\n' "$token" | curl -s -o "$body_file" -w '%{http_code}' --max-time 15 \
        -X POST -H @- -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
        --data "$1" "$url/mcp" || true
    }
    init='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"nchito-runner-check","version":"1"}}}'
    code="$(mcp_post "$init")"
    gateway_up=""
    case "$code" in
      200) if grep -q serverInfo "$body_file"; then ok "POST /mcp initialize -> 200, token accepted"; gateway_up=1
           else fail "POST /mcp -> 200 but no serverInfo in the reply"; fi ;;
      401) fail "POST /mcp -> 401: token rejected (unknown, revoked or mistyped)" ;;
      429) warn "POST /mcp -> 429: too many calls from this token; try again in a minute" ;;
      307|308) fail "POST /mcp -> $code redirect: check NCHITO_URL (scheme, host, no path)" ;;
      *) fail "POST /mcp -> ${code:-no answer}" ;;
    esac
    if [ -n "$gateway_up" ]; then
      code="$(mcp_post '{"jsonrpc":"2.0","id":2,"method":"tools/list"}')"
      if [ "$code" != "200" ]; then fail "tools/list -> ${code:-no answer}: no tool list from the gateway"
      else
        missing=""
        for t in $expected_tools; do
          grep -Eq "\"name\": ?\"$t\"" "$body_file" || missing="$missing $t"
        done
        if [ -n "$missing" ]; then fail "the gateway lacks$missing: update Nchito or this runner kit"
        else ok "tools/list: all $(echo $expected_tools | wc -w | tr -d ' ') expected gateway tools present"; fi
        if [ -n "${py:-}" ]; then  # tools the kit does not know yet (needs python to read the list)
          extra="$("$py" -c '
import json, sys
names = [t["name"] for t in json.load(open(sys.argv[1], encoding="utf-8"))["result"]["tools"]]
print(" ".join(n for n in names if n not in sys.argv[2].split()))' "$body_file" "$expected_tools" 2>/dev/null || true)"
          [ -z "$extra" ] || warn "the gateway has tools this kit does not know: $extra (update the kit)"
        fi
      fi
      code="$(mcp_post '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_runner_config","arguments":{}}}')"
      if [ "$code" != "200" ]; then fail "get_runner_config -> ${code:-no answer}"
      elif grep -Eq '"isError": ?true' "$body_file"; then fail "get_runner_config refused: $(head -c 300 "$body_file")"
      elif grep -Eq '"enabled": ?false' "$body_file"; then fail "this runner is switched off or suspended: see Settings, Runners"
      elif grep -Eq '"enabled": ?true' "$body_file"; then ok "get_runner_config: runner enabled"
      else fail "get_runner_config: unreadable reply"; fi
    fi
    rm -f "$body_file"
  fi
fi

if [ "$failed" -gt 0 ]; then echo "$failed check(s) failed."; exit 1; fi
[ -n "$quiet" ] || echo "All checks passed (warnings above, if any, need a look)."
exit 0
