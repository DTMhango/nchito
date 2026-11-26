# Runbook

Operating one Nchito instance. Sections marked *(wave 2)* are completed when backups,
restore-paused and reconciliation land; backups, retention, notifications and health are described as built.

## Services

| Service | Command | Health |
|---|---|---|
| `db` | PostgreSQL 16 | `pg_isready` |
| `migrate` | `nchito migrate` (Alembic upgrade + built-in themes), exits | exit code 0 |
| `web` | `nchito web` (uvicorn, port 8000) | `GET /api/health` returns 200 |
| `worker` | `nchito worker` (Procrastinate worker, scheduler tick every minute, heartbeat) | `nchito worker-alive` (heartbeat newer than `WORKER_STALE_AFTER_SECONDS`, default 180) |

`/api/health` reports `status: ok | degraded | down`: `degraded` means the database answers
but no worker heartbeat is fresh; `down` (HTTP 503) means the database is unreachable.

## First start (local)

    cp .env.example .env    # set SECRET_KEY; ENCRYPTION_KEY can stay empty in development
    docker compose up -d --build
    open http://localhost:8000

## First run

1. **Create the owner.** Open the app: with no owner yet it shows the setup page
   (`POST /api/setup/owner`). Pick a long passphrase; there is one owner per instance.
2. **Wizard.** Onboarding walks through the Kit (import a `.kit.zip` or the old job-hunting folder,
   or start empty), the profile, work rights and answers, the first track and campaign, the theme
   (built-in or one made in the Theme studio) and the autopilot mode (start in *review*).
   Every imported fact, skill and guardrail starts *to review*; nothing is used until you confirm it.
3. **Connect Gmail (and Drive, Calendar).** In Google Cloud console create one OAuth client
   (type *Web application*) and set `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET`.
   Enable the **Gmail API**, **Google Drive API** and **Google Calendar API** for the project, and
   register these redirect URIs (`BASE_URL` is the public address, e.g. `http://localhost:8000`):
   - `BASE_URL/api/connections/oauth/gmail/callback` (scopes `gmail.send`, `gmail.readonly`)
   - `BASE_URL/api/connections/oauth/gdrive/callback` (scope `drive.file`, backups and exports)
   - `BASE_URL/api/connections/oauth/gcalendar/callback` (scope `calendar.app.created`)

   While the consent screen is in *testing*, add your own address as a test user. Then
   Settings → Connections → Connect. Outlook/OneDrive: see "Outlook and OneDrive" below.
4. **Try it without real postings.** `docker compose exec web nchito demo-job` (or
   `python -m app.cli demo-job` in `backend/`) inserts one fictional role so you can walk
   score → tailor → approve → send-by-hand end to end. It is refused in production.
5. **PC runner** (portals that need a browser): see "Local runner" below; pair it from
   Settings → Runners. The optional server runner is under "Server runner".
6. **Backups.** Set the backup target (local folder, S3, Google Drive or OneDrive) in Settings →
   Data, run `nchito backup` once and test a restore (see "Backups and restore"). Keep
   `ENCRYPTION_KEY` outside the server.

## First start (VPS, Dokploy)

1. Create a Compose app in Dokploy from this repository, compose file `docker-compose.dokploy.yml`.
2. Environment: `DOMAIN`, `SECRET_KEY` (long random), `POSTGRES_PASSWORD`, `ENCRYPTION_KEY`
   (`docker run --rm <image> nchito gen-key`), optionally `APP_NAME`, `S3_*` and
   `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` (one Google OAuth client for both the Gmail and the
   Drive connection; register `https://$DOMAIN/api/connections/oauth/gmail/callback` and
   `.../oauth/gdrive/callback` as redirect URIs), `MS_OAUTH_CLIENT_ID` / `MS_OAUTH_CLIENT_SECRET` /
   `MS_OAUTH_TENANT` (see "Outlook and OneDrive").
3. Deploy. Traefik routes `https://$DOMAIN` to `web:8000` on the `dokploy-network`.
4. Keep a copy of `ENCRYPTION_KEY` outside the server. It is never stored in the database or
   in backups; without it, stored provider tokens cannot be decrypted and must be reconnected.

Minimum VPS: 2 GB RAM without the server runner, 4 GB with it (to confirm in the wave 3 spike).

## Upgrades

    git pull && docker compose up -d --build

`migrate` runs before `web` and `worker` start. Migrations are forward-only in production;
`alembic downgrade` exists for development. The Procrastinate queue schema was created by the
first migration; when upgrading Procrastinate across a schema change, add an Alembic migration
that applies its SQL migration files (`procrastinate schema --migrations-path`).

## Common tasks

| Task | Command |
|---|---|
| Logs | `docker compose logs -f web worker` |
| Shell in the app | `docker compose exec web sh` |
| psql | `docker compose exec db psql -U nchito nchito` |
| New encryption key | `docker compose run --rm web nchito gen-key` |
| Regenerate contracts (dev) | `cd backend && python -m app.cli contracts` |
| Reset the owner password | not available by design in wave 0; restore from backup or delete the `owner` row in psql (sessions cascade), then run setup again |

## Settings

Business settings (thresholds, caps, quiet hours, models, budgets, themes) are changed in the
app (Settings) and are versioned and audited. Deployment settings are env vars listed in
`.env.example`. Changing env requires `docker compose up -d` to recreate the containers.

## Backups and restore

**What a backup is.** One file, `nchito-<UTC time>.backup`, in `BACKUP_DIR` (default `./data/backups`; in
Docker mount a volume at `/data/backups` and set `BACKUP_DIR=/data/backups`). It is a tar of `manifest.json`,
`db.dump` (`pg_dump`, custom format) and `files/` (the vault, documents and submitted snapshots; `files/tmp` is
skipped), encrypted with Fernet using `ENCRYPTION_KEY`. The key is **not** in the backup: keep a copy of it
elsewhere, or the backup cannot be opened. The dump and the row counts in the manifest come from one snapshot,
so a restore is checked against them exactly.

**Schedule and keep.** Nightly by `backups.cron` (default 02:00 in the owner's time zone); `backups.keep`
copies are kept (default 14; older ones are deleted together with their remote copy). `backups.target` `gdrive` also
uploads each archive to the connected Google Drive folder (`backups/`); `local` only writes locally. A failed upload
keeps the local copy and marks the run partial. The `s3` target is not available in this build: the backup stays
local. `pg_dump` and `pg_restore` must be in the image (`postgresql-client`, the same major version as the database;
set `PG_BIN_DIR` if they are not on PATH). `backups.target` `onedrive` uploads to the connected OneDrive app folder
the same way. Run one now with Settings, Data, or `nchito backup`.

**Restore (new or wiped server).**

    # 1. same ENCRYPTION_KEY in the environment as when the backup was made
    docker compose up -d db
    nchito restore /path/nchito-20261126T000000Z.backup --inspect     # shows date, schema revision, file count
    nchito restore /path/nchito-20261126T000000Z.backup --yes         # replaces data in DATABASE_URL and FILES_DIR
    nchito migrate                                                    # only if this release is newer than the backup
    docker compose up -d

What it does, in order: decrypts and unpacks to a temporary folder; checks the vault hash; loads the database in one
transaction (`--clean --if-exists`); compares every table's row count with the manifest; moves the current files
folder aside to `<FILES_DIR>.before-restore-<time>` (never deletes it) and puts the backup's files in place; sets
`automation.paused` and audits `backup.restored`. If the PostgreSQL client tools are newer than the server and
`pg_restore` rejects a setting, the restore falls back to `psql`, which gives the same result. A wrong key, a damaged
file or a manifest mismatch stops before anything is replaced.

To rehearse: `nchito restore <file> --yes --database-url postgresql://user:pw@host/scratch --files-dir /tmp/scratch-files`.

- **An instance started from a restored backup starts paused** (`nchito restore` does this itself; `nchito restored
  --backup-taken-at <time>` repeats it by hand, e.g. after a restore into an older schema and `nchito migrate`): sends
  that were in flight at backup time become uncertain and are reconciled against the mailbox's sent items, and
  approvals of roles that were ready but unsent are withdrawn (the old instance may have sent them after the backup).
  `GET /api/autopilot/restore` lists what is outstanding; `POST /api/autopilot/resume-after-restore` is refused until
  it is empty (settle any by hand with a dispatch's `reconcile`). Never resume before checking the reconciliation list.

## Outlook and OneDrive (Microsoft sign-in)

One Microsoft Entra app registration serves both connections.

1. Entra admin center (entra.microsoft.com), App registrations, New registration. Supported account types: pick
   "personal Microsoft accounts only" for `MS_OAUTH_TENANT=consumers`, or "any directory and personal accounts"
   for `common` (the default). Platform: Web.
2. Redirect URIs (exact, one per connection): `BASE_URL/api/connections/oauth/msgraph/callback` and
   `BASE_URL/api/connections/oauth/onedrive/callback`.
3. API permissions, Microsoft Graph, Delegated: `offline_access`, `User.Read`, `Mail.Send`, `Mail.Read` (Outlook)
   and `Files.ReadWrite.AppFolder` (OneDrive). Nothing else is requested, and no admin consent is needed for a
   personal account.
4. Certificates and secrets, New client secret. Put the value (not the id) in `MS_OAUTH_CLIENT_SECRET` and the
   Application (client) id in `MS_OAUTH_CLIENT_ID`; `MS_OAUTH_TENANT` defaults to `common`. Restart the stack.
   Until both are set, Connect answers "set MS_OAUTH_CLIENT_ID/SECRET".
5. Settings, Connections, Connect Outlook / Connect OneDrive. For Outlook, then use Change to name the one folder
   the app may read (Mail.Read covers the whole mailbox; the app reads only that folder and Sent Items).

Notes. Microsoft keeps the app folder (`Apps/<app name>` in OneDrive) only for personal OneDrive accounts: a work
or school OneDrive refuses it and the test says so. Outlook sends through a draft so the message carries the
`X-Nchito-Idempotency-Key` header and a fixed Message-ID; a send that times out is never resent, it is settled from
Sent Items. Attachments over 3 MB are refused on Outlook. When more than one mailbox is connected, "Use as default"
on the card sets `mail.default_mailbox`; backups go to `backups.target`.

## Retention

`retention.cron` (default 04:30) runs: below-threshold roles lose their full text after
`retention.below_threshold_text_days`; roles never applied to archive after `retention.unsubmitted_archive_days`;
notifications older than `retention.notifications_days` and files in `FILES_DIR/tmp` older than
`retention.temp_files_days` are deleted; backups beyond `backups.keep` are pruned. It never deletes applications,
packets, permits, dispatch attempts, the audit, sightings, the ledger or the vault; the run counts those tables
before and after and rolls back if any row went missing. Run it now with Settings, Data, or
`POST /api/data/retention/run`.

## Local runner

The PC runner is Claude Code with the Claude in Chrome extension, working the gateway queue in your own Chrome
(DESIGN 8.3). The kit is `runner/local/`.

1. Prerequisites: Claude Code signed in with your Claude subscription (`/login`, not an API key), Google Chrome with
   the Claude extension signed in to the same account, and `/chrome` run once in Claude Code.
2. In Nchito, Settings, Runners: create a runner token (shown once).
3. Install (copies the skill to `%USERPROFILE%\.claude\skills\nchito-queue`, config and scripts to
   `%USERPROFILE%\.nchito-runner`, saves `NCHITO_URL` and the token as user environment variables, never in a file):
   `powershell -NoProfile -ExecutionPolicy Bypass -File runner\local\install.ps1 -Url https://<instance> -SetToken`
   (bash: `runner/local/install.sh`, with both variables already exported).
4. Open a new terminal. Self-check (config, `/api/health/live`, the token against `/mcp`: `tools/list` compared with
   the 12 tools the kit expects, and `get_runner_config` says this runner is not suspended):
   `powershell -File "$env:USERPROFILE\.nchito-runner\check.ps1"`.
5. First run, a dry run (reads one form, types nothing, requests no permit):
   `powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\.nchito-runner\start.ps1" -Arguments dry-run`.
   It claims with `next_task(dry_run)`, types and submits nothing, and gives the task back with `release_task`.
6. Work the queue (one line): `powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\.nchito-runner\start.ps1"`.
   It stops when the queue is empty. `-Arguments "max=5"` limits a run.
7. Unattended: `runner/local/UNATTENDED.md` (spike report). Recommended: a sign-in Task Scheduler entry that keeps a
   visible `/loop` session open, registered with `%USERPROFILE%\.nchito-runner\scheduled\register-task.ps1`
   (`-Remove` to undo). The PC must stay awake and signed in.

The runner never types passwords, creates accounts, solves CAPTCHAs or enters codes: those arrive as pending actions
(sign in, then "I've signed in, continue"). Logs: `%USERPROFILE%\.nchito-runner\logs`; packet files and screenshots:
`...\work`. To stop it at once, pause Autopilot or revoke the runner token; then close the window.

## Notifications, digest and health alerts

Channels: Telegram (bot token from BotFather and your chat id), a signed webhook, and email (mail stream). Add them
in Settings, Connections, then list them in `notifications.channels`. Telegram buttons are links into the app;
approving always needs your signed-in session. `notifications.events` chooses what notifies; quiet hours
(`notifications.quiet_hours_*`) hold messages until they end; `notifications.detail_level` `generic` keeps role and
employer names out of Telegram. A failed send is retried (`notifications.retry_attempts`, doubling from
`notifications.retry_minutes`) and then audited as `notification.delivery_failed`; it never stops a sweep. The digest
is sent once a day, after the daily sweep or at `notifications.digest_time` (`notifications.digest`).

`GET /api/health/live` and `/ready` are for the platform; `/api/health/detail` (signed in) shows worker heartbeat age,
last successful sweep and backup, disk, queue depth and each connection. One alert is raised when a component starts
failing and one when it recovers. Webhook receivers verify `X-Nchito-Signature` (HMAC-SHA256 of
`"<X-Nchito-Timestamp>.<body>"`) and may drop a repeated `X-Nchito-Event-Id`.

## Server runner (optional)

An optional container that works **account-free** application forms (Greenhouse, Lever, Ashby, Teamtailor, BambooHR
style) headlessly, using the Claude Agent SDK and Playwright Chromium. It is off by default and costs API tokens, so it
has its own budget line. Forms that need a sign-in, account, CAPTCHA or assessment stay with the PC runner: the server
runner raises a blocker and moves on. Sizing: plan 4 GB RAM on the VPS with it running (2 GB without).

**Turn it on**

1. Settings, Runners: create a runner token (shown once) and turn on `runners.server_runner_enabled`.
2. Set `RUNNER_TOKEN` (that token), `RUNNER_ANTHROPIC_API_KEY` and, if you want, the budget values below in the
   environment (Dokploy environment, or `.env` locally).
3. `docker compose --profile runner up -d --build runner` (add `-f docker-compose.dokploy.yml` on the VPS). Plain
   `docker compose up` never starts it.
4. Settings, Runners shows its last-seen time within a minute. Logs: `docker compose logs -f runner`.

**Environment.** The same two names everywhere (PC runner, server runner, check scripts):
`NCHITO_URL` (the instance, for example `https://nchito.example.com`; the gateway is `$NCHITO_URL/mcp`) and
`NCHITO_RUNNER_TOKEN` (`nch_...`). In compose the server runner's come from `RUNNER_NCHITO_URL` (default
`http://web:8000`, the compose network) and `RUNNER_TOKEN`. `runner/server/nchito_runner/config.py` holds the one
default for each of the rest; compose leaves them empty unless you set them.

| Variable (compose name) | Default | Meaning |
|---|---|---|
| `NCHITO_URL` (`RUNNER_NCHITO_URL`) | `http://web:8000` in compose | The instance as the runner reaches it, no `/mcp`, no trailing slash |
| `NCHITO_RUNNER_TOKEN` (`RUNNER_TOKEN`) | none, required | Runner token from Settings, Runners |
| `ANTHROPIC_API_KEY` (`RUNNER_ANTHROPIC_API_KEY`) | none, required | Its own key, so its spend is separate |
| `RUNNER_TASK_MAX_COST_USD` / `RUNNER_DAY_MAX_COST_USD` | 1.0 / 10.0 | Ceilings on the owner's cost caps, per task and per UTC day |
| `RUNNER_TASK_MAX_TOKENS` / `RUNNER_DAY_MAX_TOKENS` | 600000 / 6000000 | Ceilings on the owner's token caps |
| `RUNNER_POLL_SECONDS` | 30 | Idle poll interval |
| `RUNNER_TASK_KINDS` | `apply,check_posting` | Task kinds it takes (sweeps stay with the PC runner) |
| `RUNNER_DRY_RUN` | 0 | 1 = rehearsal: `next_task(dry_run)`, never a permit, every task released at the end |

**Owner's settings first.** Before every claim the runner calls `get_runner_config`: it claims nothing while
`runners.server_runner_enabled` is off or its token is suspended, drives the browser with `ai.model_browser_agent`,
stops at `automation.agent_max_steps`, and keeps screenshots under `runners.evidence_max_kb`. Its caps are the owner's
(`budget.agent_task_ceiling_minor`, `runners.server_day_cap_minor`, `runners.server_task_max_tokens`,
`runners.server_day_max_tokens`) under the environment ceilings above: the environment can only tighten them. Money
caps are compared only when `budget.currency` is USD (what the Agent SDK reports); in another currency the cost
ceilings above apply and the token caps follow the owner. The server enforces steps and the task ceiling again on its
side. A cap of 0 means no spend.

**What it will not do (enforced in code, not only in the prompt)**

- Never types into a password field, and never creates an account.
- Never navigates away from the posting's domain; a redirect or off-site link raises `redirect_off_domain` and ends the task.
- Never clicks the submit control (or presses Enter) without a granted, unexpired, unused permit held in memory for that
  task; a document-level form POST is also aborted at the network layer without one. In a multi-step form a
  submit-type "Next" moves on without a permit only when the page shows more steps follow ("Step 1 of 3", or required
  fields of a later step not shown yet); if that click would post the form after all, the post is aborted. Unsure is
  the submit.
- Never uploads anything except the task packet's files (matching hash, never a `never` file), and fetches them only
  from the gateway's signed `/api/gateway/files/` links on `NCHITO_URL` (the browser never visits that host).
- Page text reaches the model only inside a marked untrusted-data block; the model has no shell, file or web tools.
- Before a submit click it records a "submit attempted" checkpoint. If it restarts and finds that checkpoint, it
  reports `uncertain` and never submits again; `uncertain` goes to reconciliation.

**Evidence.** Screenshots (before the submit click, of the confirmation page, of a checked posting) are uploaded
through `evidence_upload_url` and referenced as `evidence:<task>/<id>`; nothing is kept on the runner's volume.

**Budget exhausted.** At the task cap the task is reported `failed` with "budget line exhausted". At the day cap the
current task is checkpointed and released (`release_task`) to resume later, no new task is claimed, and the runner
waits (the ledger is `/data/state/budget.json`, so a restart does not reset it).

**Stopping.** `docker compose stop runner` (SIGTERM) saves a checkpoint for the task in hand and gives it back with
`release_task`; it resumes from that checkpoint. A task already cleared to submit is never released: it is reported
(`uncertain` after a click, `failed` before one). Volumes: `/data/profile` (Chromium profile), `/data/state` (budget
ledger). The heartbeat is an MCP ping (last-seen); a task's lease (`runners.task_lease_minutes`) is kept by its tool
calls.

**Testing against the real gateway.** `backend/tests/integration/test_runner_gateway.py` drives the runner's own
gateway client, worker and Toolbox against the backend app in process (test database on 127.0.0.1:55442) with a
scripted model and a static form in real headless Chromium: one submit with the CV and evidence, the application
`submitted` and its audit chain; a dry run denied and released; a new question held for the owner; a second runner
neither claims nor gets a permit. It needs the backend and the runner in one environment on one `mcp` 1.x (the runner
pins `mcp>=1.30,<2`, the version the gateway runs); the backend's normal suite skips it when `nchito_runner` is not
installed:

    python -m venv .venv-runner-it
    .venv-runner-it/Scripts/pip install -e "./backend[dev]" -e "./runner/server[dev]"   # bin/ on Linux
    .venv-runner-it/Scripts/playwright install chromium
    cd backend && ../.venv-runner-it/Scripts/python -m pytest tests/integration/test_runner_gateway.py

The runner's own tests (`cd runner/server`, a venv at `runner/server/.venv` with `pip install -e ".[dev]"` and
`playwright install chromium`, then `pytest -n 4`) use a fake gateway with the same tool list.

## Incidents

| Symptom | Check | Action |
|---|---|---|
| `/api/health` degraded | `docker compose ps worker`, `logs worker` | restart the worker; scheduled runs missed during downtime run once (or are skipped, per `schedule.missed_run`) |
| Runs stuck `queued` | `select * from procrastinate_jobs where status in ('todo','doing')` | restart the worker; stalled jobs are retried by Procrastinate |
| Something is being sent that should not be | Autopilot switch in the top bar (pause) | pause stops new outward actions and cancels queued sends at once *(wave 2)* |
| A runner submitted without a permit | Settings, Runners | its token is suspended automatically *(wave 3)*; review, then reinstate or revoke |
