# Spike report: running the local runner unattended

Wave 3, 26 Nov 2026. DESIGN.md 8.3 asks for the best working way to let Claude Code with
Claude in Chrome work the Nchito queue on the owner's Windows PC without the owner starting
it each time. Three options were examined: a Claude desktop-app scheduled task, a Windows Task
Scheduler entry launching Claude Code, and a long-lived `/loop` session.

**Nothing here was run against a real browser.** The build environment cannot drive Chrome.
Every claim below is marked:

- **Documented**: stated in Anthropic's official docs (sources at the end), read on 26 Nov 2026.
- **Assumed**: follows from documented behaviour but is not stated; likely, unproven.
- **Owner to try**: unknown until tried on the PC. The test is given.

Commands below write paths as `%USERPROFILE%`, which works in Task Scheduler and `cmd`. In
PowerShell write `$env:USERPROFILE` instead.

## Facts that decide it

| # | Fact | Status |
|---|---|---|
| F1 | Chrome integration is started with `claude --chrome` (or `/chrome` "enabled by default"). Needs Chrome with the Claude extension 1.0.36+, and a direct Anthropic plan (Pro, Max, Team, Enterprise) signed in with `/login`. Windows is supported; WSL is not. | Documented |
| F2 | With an API key (`ANTHROPIC_API_KEY`) or a `claude setup-token` token (`CLAUDE_CODE_OAUTH_TOKEN`), Claude Code keeps Chrome off even with `--chrome`. So unattended runs must use the normal subscription login. | Documented |
| F3 | On Windows the subscription login is stored in `%USERPROFILE%\.claude\.credentials.json`. Using Claude Code does not extend it; `claude auth status --text` shows when it ends. | Documented |
| F4 | A process started by Task Scheduler as the same signed-in user reads the same login file. | Assumed |
| F5 | Browser actions run in a visible Chrome window; Claude "pauses" at login pages and CAPTCHAs for the user to handle. | Documented (interactive use) |
| F6 | `claude -p` (print, headless) together with `--chrome`. | **Not documented.** The Chrome page describes interactive use only. Owner to try. |
| F7 | `/loop <interval> <prompt>` repeats a prompt in an open session while it is idle; it is session-scoped, does not survive the session closing or a restart, and expires 30 days after it is created (7 days before Claude Code 2.1.330; this PC had 2.1.310 on 26 Nov 2026, so update first). | Documented |
| F8 | A prompt given on the command line (`claude "/nchito-queue"`) starts an interactive session with that prompt; slash commands and user skills are expanded, also in `-p`. | Documented |
| F9 | Permission mode `dontAsk` denies anything that would prompt; tools on `--allowedTools` still run. MCP tools are allowed as `mcp__<server>__*`. | Documented |
| F10 | Desktop-app local scheduled tasks run on the PC "only while the app is open and your computer is awake", hourly at most often, with a per-task permission mode; one catch-up run for missed times. | Documented |
| F11 | Whether a desktop-app scheduled task can reach Claude in Chrome. | **Not documented.** Owner to try. |
| F12 | The extension's per-site approval: the first action on a site may ask "Claude in Chrome wants to ..." with "allow all actions on this site for this session". Under `dontAsk`/`auto`, whether that dialog is skipped or blocks. | Partly documented (auto mode can skip it when the classifier approves). **Owner to try** under `dontAsk`. |
| F13 | Cloud scheduled tasks ("routines", `/schedule`) run on Anthropic's machines and cannot reach the owner's Chrome. | Documented (they use claude.ai connectors and a fresh clone); ruled out. |

## Option A: desktop-app scheduled task

How: Claude desktop app, Scheduled tasks, New task, "Only on this computer", folder
`%USERPROFILE%\.nchito-runner\work`, schedule Hourly (or Custom cron, at most hourly),
permission mode "Don't ask" if offered (otherwise accept prompts the first time), prompt:

    /nchito-queue

The MCP server must be available to the app: register it at user scope once (the token stays
an environment-variable reference in `~/.claude.json`):

    # PowerShell: the URL is expanded now, the token placeholder is kept literally
    claude mcp add --transport http -s user nchito "$env:NCHITO_URL/mcp" --header 'Authorization: Bearer ${NCHITO_RUNNER_TOKEN}'

(Assumed: user-scope entries expand `${VAR}` the same way `.mcp.json` does. If the check shows
the literal text being sent, use the desktop app's MCP settings instead.)

- For: built-in, no scripts, catch-up of a missed run, "keep computer awake" setting.
- Against: Chrome reachability is undocumented (F11); needs the app open; hourly at most;
  each run is a fresh session that reloads tools.
- Verdict: **second choice.** Worth a 10-minute test (below); if it reaches Chrome it is the
  least moving parts.

## Option B: Task Scheduler launching `claude -p`

How: a task every 30 minutes (only while signed in) running

    powershell -NoProfile -ExecutionPolicy Bypass -File "%USERPROFILE%\.nchito-runner\start.ps1" -Print -Unattended -Arguments "max=10" -MaxTurns 400

which runs `claude -p "/nchito-queue max=10" --chrome --mcp-config ... --permission-mode dontAsk
--allowedTools ... --output-format json` and logs to `logs\run-*.json`. To use it, register the
task as in option C and change the `<Arguments>` line in Task Scheduler to the command above,
and set a repetition of 30 minutes on the trigger.

- For: one clean process per run, a JSON log per run, nothing left running between runs.
- Against: `-p` with `--chrome` is undocumented (F6); the extension's first-run and per-site
  dialogs are interactive and may block a headless run (F12). If it fails, it fails silently
  except for the log.
- Verdict: **use only if the owner's test shows it works.** It would then be the tidiest.

## Option C: a long-lived `/loop` session, started by Task Scheduler (recommended)

How: Task Scheduler starts, at sign-in and each morning if it has stopped, a visible
PowerShell window running

    powershell -NoProfile -ExecutionPolicy Bypass -File "%USERPROFILE%\.nchito-runner\start.ps1" -Loop 30m -Unattended

which runs the self-check and then the **interactive** session

    claude "/loop 30m /nchito-queue" --chrome --mcp-config "%USERPROFILE%\.nchito-runner\mcp.json" --permission-mode dontAsk --allowedTools "mcp__nchito__*" "mcp__claude-in-chrome__*" ... --disallowedTools "mcp__claude-in-chrome__javascript_tool" Edit Write ...

Every 30 minutes, when idle, the session works the queue until it is empty or blocked, then
waits for the next tick.

- For: uses only documented pieces: interactive `--chrome` (the baseline that is known to
  work), a command-line prompt (F8), `/loop` (F7), `dontAsk` with an allow list (F9). The
  owner can glance at the window at any time and type into it. Signed-in portals stay signed
  in because it is the owner's own Chrome.
- Against: the PC must be on, awake and signed in (screen locked is assumed fine; sleep is
  not). `/loop` expires after 30 days (7 on Claude Code older than 2.1.330: run `claude update`), and the window can be closed by accident: the daily
  07:00 trigger relaunches it only if the PowerShell window has exited. One long session
  builds up context; Claude Code compacts it automatically (assumed adequate for 30-minute
  ticks). The per-site dialog question (F12) applies here too, but here the owner can answer
  it once in the window and choose "allow for this session".
- Verdict: **recommended.**

## Recommendation

Use **option C** now. Install it with:

    powershell -NoProfile -ExecutionPolicy Bypass -File runner\local\install.ps1 -Url https://<instance> -SetToken
    powershell -NoProfile -ExecutionPolicy Bypass -File "%USERPROFILE%\.nchito-runner\scheduled\register-task.ps1" -Interval 30m

The task definition is `scheduled/nchito-runner.task.xml` (filled in and registered by
`scheduled/register-task.ps1`; `-Remove` takes it away). Keep the PC from sleeping while the
runner should work (Settings, System, Power: "When plugged in, put my device to sleep: Never",
or a schedule the owner prefers).

Revisit after the owner's tests: if B works headless, switch to B (no long-lived session); if
A reaches Chrome, A is simpler still. The UI shows the runner's last-seen time whichever is
used (DESIGN 8.3).

## Tests for the owner (in order)

1. **Baseline.** `start.ps1 -Arguments dry-run` in a terminal. Expect a field-by-field table
   and no typing in the form. Answer any Chrome dialogs. This proves Chrome, the skill and the
   gateway together.
2. **No prompts.** `start.ps1 -Arguments dry-run -Unattended`. Expect the same table with no
   permission prompt in the terminal. If a Chrome per-site dialog still appears, note which;
   choosing "allow for this session" is fine for option C.
3. **Option C.** `register-task.ps1 -Interval 10m`, then
   `Start-ScheduledTask -TaskPath '\Nchito\' -TaskName 'Nchito runner'`. Expect a window that
   runs the self-check, starts Claude Code and works the queue every 10 minutes. Lock the
   screen for 30 minutes and check the runner's last-seen time in Nchito. Then set it back to
   `-Interval 30m`.
4. **Option B.** `start.ps1 -Print -Unattended -Arguments dry-run -MaxTurns 200` and read
   `logs\run-*.json`. Works if the result shows the dry-run table; fails if it reports no
   browser tools or hangs (stop it after 10 minutes).
5. **Option A.** Create the desktop task above with prompt `/nchito-queue dry-run` and "Run
   now". Works if it produces the dry-run table.
6. **Login lifetime.** `claude auth status --text` and note "Sign-in ends". Put a reminder a
   few days before it; unattended runs stop working when it lapses (F3).

## What can go wrong unattended, and what happens

| Event | Effect |
|---|---|
| Subscription login expires | Claude Code cannot start a turn; nothing is claimed. Re-login with `/login`. |
| `ANTHROPIC_API_KEY` set system-wide | Chrome off (F2). `start.ps1` removes it for its own process and the self-check warns. |
| Chrome closed or extension signed out | The skill claims nothing and says "Chrome is not connected". |
| A portal needs sign-in, a CAPTCHA, a code | `raise_blocker`; the owner gets a pending action and continues later (DESIGN 8.4). |
| A permission prompt would appear | Denied under `dontAsk`; the step fails rather than waits. |
| Runner token revoked or suspended | Self-check fails, the session does not start (C) or the skill stops at the first refusal. |
| PC asleep | Nothing runs; the task's `StartWhenAvailable` and the daily trigger restart it after wake if it had exited. |

## Sources

- Claude in Chrome with Claude Code: https://code.claude.com/docs/en/chrome
- CLI flags: https://code.claude.com/docs/en/cli-reference
- Headless (`-p`): https://code.claude.com/docs/en/headless
- Permission modes and rules: https://code.claude.com/docs/en/permission-modes , https://code.claude.com/docs/en/permissions
- Authentication: https://code.claude.com/docs/en/authentication
- Desktop scheduled tasks: https://code.claude.com/docs/en/desktop-scheduled-tasks
- `/loop`: https://code.claude.com/docs/en/scheduled-tasks
- Cloud scheduled tasks: https://code.claude.com/docs/en/routines
- MCP config and `${VAR}` expansion: https://code.claude.com/docs/en/mcp
- Skills: https://code.claude.com/docs/en/skills
- Extension help: https://support.claude.com/en/articles/12012173-getting-started-with-claude-in-chrome
