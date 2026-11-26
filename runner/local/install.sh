#!/usr/bin/env bash
# Install the Nchito local runner for the current user (Git Bash on Windows, macOS, Linux).
#
#   bash runner/local/install.sh
#
# Copies the nchito-queue skill to ~/.claude/skills/nchito-queue and the MCP config, start
# and check scripts to ~/.nchito-runner (override with NCHITO_RUNNER_HOME). It does not store
# the token: set NCHITO_URL and NCHITO_RUNNER_TOKEN in your environment (on Windows, install.ps1
# -SetToken saves them as user variables, which Git Bash inherits).
set -euo pipefail

src="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
runner_home="${NCHITO_RUNNER_HOME:-$HOME/.nchito-runner}"
skill_dest="$HOME/.claude/skills/nchito-queue"

echo "Prerequisites"
if ! command -v claude >/dev/null 2>&1; then
  echo "  FAIL  Claude Code (claude) is not on PATH. Install it first: https://code.claude.com/docs" >&2
  exit 1
fi
echo "  claude: $(claude --version 2>/dev/null | head -n 1)"
if ! command -v curl >/dev/null 2>&1; then
  echo "  FAIL  curl is required" >&2
  exit 1
fi
echo "  Claude in Chrome extension: cannot be checked from here. Install it from the Chrome Web Store,"
echo "  sign in with the same Claude account as Claude Code, then run /chrome once in Claude Code."
for name in ANTHROPIC_API_KEY CLAUDE_CODE_OAUTH_TOKEN; do
  if [ -n "${!name:-}" ]; then
    echo "  warn  $name is set: Claude Code keeps Chrome off with it; start.sh drops it for runner sessions."
  fi
done
[ -n "${NCHITO_URL:-}" ] || echo "  warn  NCHITO_URL is not set (export NCHITO_URL=https://<your instance>)"
[ -n "${NCHITO_RUNNER_TOKEN:-}" ] || echo "  warn  NCHITO_RUNNER_TOKEN is not set (keep it out of any repo)"

echo "Files"
mkdir -p "$skill_dest" "$runner_home/work" "$runner_home/logs" "$runner_home/scheduled"
rm -rf "$skill_dest/reference"
cp -R "$src/skills/nchito-queue/." "$skill_dest/"
echo "  skill -> $skill_dest"
cp "$src/mcp.template.json" "$runner_home/mcp.json"
for f in start.ps1 check.ps1 start.sh check.sh; do cp "$src/$f" "$runner_home/$f"; done
chmod +x "$runner_home/start.sh" "$runner_home/check.sh"
cp "$src/scheduled/"* "$runner_home/scheduled/"
echo "  config and scripts -> $runner_home"

echo "Self-check"
status=0
"$runner_home/check.sh" || status=$?

echo
echo "Start the runner (one line):"
echo "  \"$runner_home/start.sh\""
echo "First time, a dry run (reads one form, enters nothing):"
echo "  \"$runner_home/start.sh\" dry-run"
exit "$status"
