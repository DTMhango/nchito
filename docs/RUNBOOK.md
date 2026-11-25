# Runbook

Operating one Nchito instance. Sections marked *(wave 2)* are completed when backups,
restore-paused and reconciliation land; until then they describe the intended procedure.

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
   (`docker run --rm <image> nchito gen-key`), optionally `APP_NAME` and `S3_*`.
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

## Backups and restore *(wave 2)*

- Nightly `pg_dump` plus the files volume, encrypted, `backups.keep` copies (default 14), to a
  local path, an S3-compatible store or Drive (`backups.target`).
- Restore into a clean database:

      docker compose down
      docker volume rm nchito_pgdata
      docker compose up -d db
      # decrypt the dump, then:
      docker compose exec -T db pg_restore -U nchito -d nchito --clean --if-exists < nchito.dump
      # restore the files volume from the same backup
      docker compose up -d

- **An instance started from a restored backup starts paused**, reconciles its outbox against
  the mailbox's sent items, and waits for the owner to resume (DESIGN.md 18.3). Never resume
  before checking the reconciliation list.

## Incidents

| Symptom | Check | Action |
|---|---|---|
| `/api/health` degraded | `docker compose ps worker`, `logs worker` | restart the worker; scheduled runs missed during downtime run once (or are skipped, per `schedule.missed_run`) |
| Runs stuck `queued` | `select * from procrastinate_jobs where status in ('todo','doing')` | restart the worker; stalled jobs are retried by Procrastinate |
| Something is being sent that should not be | Autopilot switch in the top bar (pause) | pause stops new outward actions and cancels queued sends at once *(wave 2)* |
| A runner submitted without a permit | Settings, Runners | its token is suspended automatically *(wave 3)*; review, then reinstate or revoke |
