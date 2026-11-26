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

## First start (VPS, Dokploy)

1. Create a Compose app in Dokploy from this repository, compose file `docker-compose.dokploy.yml`.
2. Environment: `DOMAIN`, `SECRET_KEY` (long random), `POSTGRES_PASSWORD`, `ENCRYPTION_KEY`
   (`docker run --rm <image> nchito gen-key`), optionally `APP_NAME`, `S3_*` and
   `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` (one Google OAuth client for both the Gmail and the
   Drive connection; register `https://$DOMAIN/api/connections/oauth/gmail/callback` and
   `.../oauth/gdrive/callback` as redirect URIs).
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
set `PG_BIN_DIR` if they are not on PATH). Run one now with Settings, Data, or `nchito backup`.

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

## Retention

`retention.cron` (default 04:30) runs: below-threshold roles lose their full text after
`retention.below_threshold_text_days`; roles never applied to archive after `retention.unsubmitted_archive_days`;
notifications older than `retention.notifications_days` and files in `FILES_DIR/tmp` older than
`retention.temp_files_days` are deleted; backups beyond `backups.keep` are pruned. It never deletes applications,
packets, permits, dispatch attempts, the audit, sightings, the ledger or the vault; the run counts those tables
before and after and rolls back if any row went missing. Run it now with Settings, Data, or
`POST /api/data/retention/run`.

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

**Environment** (`runner/server/nchito_runner/config.py` holds the one default for each)

| Variable | Default | Meaning |
|---|---|---|
| `NCHITO_MCP_URL` | `http://web:8000/mcp` | Gateway endpoint (compose sets it from `RUNNER_MCP_URL`) |
| `NCHITO_RUNNER_TOKEN` | none, required | Bearer token (`RUNNER_TOKEN` in compose) |
| `ANTHROPIC_API_KEY` | none, required | Its own key, so its spend is separate (`RUNNER_ANTHROPIC_API_KEY` in compose) |
| `RUNNER_MODEL` | `claude-sonnet-5-5` | Model id; matches the `ai.model_browser_agent` default |
| `RUNNER_TASK_MAX_COST_USD` / `RUNNER_DAY_MAX_COST_USD` | 1.0 / 10.0 | Cost caps per task and per UTC day |
| `RUNNER_TASK_MAX_TOKENS` / `RUNNER_DAY_MAX_TOKENS` | 600000 / 6000000 | Token caps per task and per UTC day |
| `RUNNER_POLL_SECONDS` | 30 | Idle poll interval (also its last-seen signal) |

The gateway contract does not publish budget values, so the runner reads its caps from the environment. The server still
enforces `automation.agent_max_steps` and `budget.agent_task_ceiling_minor` on every task. A cap of 0 means no spend.

**What it will not do (enforced in code, not only in the prompt)**

- Never types into a password field, and never creates an account.
- Never navigates away from the posting's domain; a redirect or off-site link raises `redirect_off_domain` and ends the task.
- Never clicks the submit control (or presses Enter) without a granted, unexpired, unused permit held in memory for that
  task; a document-level form POST is also aborted at the network layer without one.
- Never uploads anything except the task packet's files (matching hash, never a `never` file).
- Page text reaches the model only inside a marked untrusted-data block; the model has no shell, file or web tools.
- After a submit click it records a "submit attempted" checkpoint first. If it restarts and finds that checkpoint, it
  reports `uncertain` and never submits again; `uncertain` goes to reconciliation.

**Budget exhausted.** At the task cap the task is reported `failed` with "budget line exhausted". At the day cap the
current task is checkpointed and left to resume, no new task is claimed, and the runner waits (the ledger is
`/data/state/budget.json`, so a restart does not reset it). Raise the cap or wait for the next UTC day.

**Stopping.** `docker compose stop runner` (SIGTERM) saves a checkpoint for the task in hand and stops pinging; the
server returns the stale claim to the queue with that checkpoint. Volumes: `/data/profile` (Chromium profile) and
`/data/state` (budget ledger and evidence screenshots).

**Known gaps (wave 3).** The contract has no heartbeat, lease-release or screenshot-upload tool. The runner uses an MCP
ping and its idle `next_task` poll as last-seen, calls `release_task` only if the server offers it, and reports the
screenshot as `runner-local:<file>#sha256=<hash>` with the file kept on `/data/state/evidence`.

## Incidents

| Symptom | Check | Action |
|---|---|---|
| `/api/health` degraded | `docker compose ps worker`, `logs worker` | restart the worker; scheduled runs missed during downtime run once (or are skipped, per `schedule.missed_run`) |
| Runs stuck `queued` | `select * from procrastinate_jobs where status in ('todo','doing')` | restart the worker; stalled jobs are retried by Procrastinate |
| Something is being sent that should not be | Autopilot switch in the top bar (pause) | pause stops new outward actions and cancels queued sends at once *(wave 2)* |
| A runner submitted without a permit | Settings, Runners | its token is suspended automatically *(wave 3)*; review, then reinstate or revoke |
