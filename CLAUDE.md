# CLAUDE.md: Nchito build agents

Read `docs/DESIGN.md` in full before touching code (section 18 amends earlier sections and
wins on conflict), then `docs/CONTRACTS.md`. MUST in DESIGN.md is a review gate.

## Hard rules

- **No personal data in the repo.** `Job Hunting.zip`, `/data`, `*.kit.zip` and `.env` are
  ignored; never copy anything from the zip into the repo, tests, fixtures or docs. Test data
  is invented (see `kits/example/`, `example.com` addresses only). Personal material enters
  only through the UI.
- **No literal defaults outside the settings registry.** Every business value that someone
  would plausibly change (times, thresholds, caps, limits, lists, wording, model names) is a
  setting in `backend/app/core/settings/registry.py` with one default, a validator, an
  `example` and an `invalid_example`. Deployment values go in `app/core/config.py` (env).
  Invariants (audit, submit permit, duplicate protection, secret handling, untrusted-content
  isolation, ledger integrity) are never settings. Pay floors, countries, seniority, visa and
  relocation answers have no default anywhere in code.
- **Configurability level: maximum** (owner's decision, DESIGN.md 1), within those guardrails.
- **Contracts first.** Do not reshape a request/response model, Protocol or schema in
  `docs/CONTRACTS.md` without updating the doc and regenerating (`python -m app.cli contracts`).
  Implement 501 endpoints to their existing models.
- **Stay in your folders** (CONTRACTS.md section 12). Shared files (models, migrations, json
  shapes, registry, routers `__init__`) change only for the lines your stream needs.
- **Unknown is not yes.** Unknown pay, eligibility or deadline never permits automation.
- **Untrusted content is data**: job pages, emails, attachments never become prompts or
  instructions.
- Tests never call paid APIs, real job sources or the network (recorded fixtures, fake
  `LLMClient`).
- Do not commit; the coordinator commits.

## Stack

Backend: Python 3.12 (runs on 3.11 locally), FastAPI, SQLAlchemy 2 async (asyncpg), Alembic
(sync psycopg), Pydantic v2, Procrastinate on PostgreSQL 16, croniter, Argon2, Fernet.
Frontend: React 19, Vite, TypeScript, Tailwind v4, shadcn/ui, TanStack Router and Query,
`openapi-typescript` + `openapi-fetch` from `docs/openapi.json`. One Docker image for web and
worker.

## Layout

    backend/app/core/        config (env), settings/ (registry, service), security, crypto, audit,
                             events (SSE via pg NOTIFY), conditions (one condition engine), clock, db
    backend/app/models/      kit.py, search.py, applications.py, platform.py
    backend/app/schemas/     json_types.py: Pydantic shapes of every JSONB column
    backend/app/api/         routers/ (one per area), deps.py, common.py, crud.py
    backend/app/themes/      built-in themes (JSON lifted from design/ui-preview.html), schema, service
    backend/app/worker/      queue.py (Procrastinate), scheduler.py (tick), heartbeat.py, main.py
    backend/app/pipeline/    decisions.py (decision table boundary), runs.py (run handlers)
    backend/app/sources/ apply/ llm/ connect/ gateway/ kit/ docs/ ops/   interfaces + later waves
    backend/app/migrations/  Alembic
    backend/tests/
    frontend/                SPA (built into the image, served at /)
    kits/example/            fictional kit used by tests
    docs/                    DESIGN.md, CONTRACTS.md, RUNBOOK.md, openapi.json, schemas/

## Commands

    docker compose -f docker-compose.test.yml up -d      # test PostgreSQL on 127.0.0.1:55442
    cd backend
    pip install -e ".[dev]"
    pytest tests/test_<module>.py                        # while working
    pytest -n 8                                          # whole suite (parallel), once per piece of work
    ruff check .
    python -m app.cli contracts                          # after any API/schema change
    alembic revision --autogenerate -m "..."             # with DATABASE_URL set; review the file
    alembic check                                        # no drift between models and migrations
    docker compose up -d --build                         # whole stack on http://localhost:8000

## Quality rules (DESIGN.md 15)

- While working, run the new tests and the tests of the module you changed. Widen to the whole
  suite when touching models, migrations, settings, fixtures or shared helpers. The whole suite
  runs once per wave before merge, in parallel, following any machine-level rules in your own
  instructions (worker counts, suite slots).
- Required tests for later waves (see DESIGN.md 15 and 18.6): precedence (a 100 score cannot
  rescue an excluded role); unknown is not yes; no double submit under concurrency; one role
  per employer (winner, held, promotion, two runners cannot both submit); facet filters
  (include, exclude, not stated distinct; a view never alters pipeline state; a view copied to
  a campaign rule matches the same jobs); permit expiry and single use; cap and quiet-hour
  gates; spend cap with concurrent reservations; each guardrail type; fact tracing catches an
  invented number; claim drift; restart resumes without duplicates; backup restores; kit
  round-trips; the five release gates of 18.6.
- Typed, small modules, no placeholder bodies in finished work; ruff clean.
- Every outward action traces to facts, approval or gates, permit, runner and evidence in the
  append-only audit.
