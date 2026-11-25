# Nchito

A private, single-owner job-hunting platform: sweep sources, score roles against your own
criteria, tailor CVs and letters from approved facts only, apply through email, a browser
agent or by hand, and track everything after. One deployment serves one person; the person
is data (the Kit), never code.

- Specification: [`docs/DESIGN.md`](docs/DESIGN.md) (section 18 amends earlier sections)
- Contracts for build agents: [`docs/CONTRACTS.md`](docs/CONTRACTS.md), [`docs/openapi.json`](docs/openapi.json)
- Operations: [`docs/RUNBOOK.md`](docs/RUNBOOK.md)
- Visual reference: [`design/ui-preview.html`](design/ui-preview.html)

**The repository contains no personal data.** Personal material enters only through the UI.

## Run it (Docker)

Requires Docker with Compose v2.

    cp .env.example .env        # optional for a local trial; set real secrets for real use
    docker compose up -d --build
    # open http://localhost:8000 and create the owner account

Services: `db` (PostgreSQL 16), `migrate` (one-shot: migrations and built-in themes), `web`
(API at `/api`, the built SPA at `/`), `worker` (queue, one-minute scheduler tick, heartbeat).
Data lives in the named volumes `pgdata` and `files`.

    docker compose ps                       # health of each service
    curl http://localhost:8000/api/health   # {"status":"ok", "db":{...}, "worker":{...}}
    docker compose logs -f worker
    docker compose down                     # stop (volumes kept)

The image builds `frontend/` when it exists; `docker compose build --build-arg SKIP_SPA=1`
builds the API-only image. VPS deployment: `docker-compose.dokploy.yml` (see the runbook).

## Develop the backend

Python 3.12 in Docker; the code also runs on 3.11.

    cd backend
    python -m venv .venv
    .venv/Scripts/activate          # Windows; on Linux/macOS: source .venv/bin/activate
    pip install -e ".[dev]"

    # a database for development
    docker compose up -d db         # or any PostgreSQL 16 you have
    set DATABASE_URL=postgresql://nchito:nchito@localhost:5432/nchito   # adjust; expose the port if needed
    python -m app.cli migrate
    python -m app.cli web --reload  # http://localhost:8000/api/docs
    python -m app.cli worker        # in another shell

## Test

Tests need PostgreSQL. Start the throwaway test server (port 55442, data in tmpfs):

    docker compose -f docker-compose.test.yml up -d

Then, from `backend/`:

    pytest -n 8                     # whole suite in parallel (pytest-xdist)
    pytest tests/test_conditions.py # one module
    ruff check .

Each xdist worker creates and migrates its own database (`nchito_t_gw0`, ...). Point
`TEST_DATABASE_URL` at another server if you prefer. Tests never call paid APIs or the network.

Stop the test database with `docker compose -f docker-compose.test.yml down`.

## Contracts

After changing any API route, model shape, theme, kit or gateway schema:

    cd backend && python -m app.cli contracts   # regenerates docs/openapi.json and docs/schemas/*.json

The frontend generates its API client from `docs/openapi.json`.

## Layout

    backend/app/    core (config, settings registry, security, crypto, audit, events, conditions),
                    models, api/routers, kit, sources, pipeline, llm, docs, apply, gateway,
                    connect, ops, themes, worker, migrations
    backend/tests/
    frontend/       React SPA
    kits/example/   a fictional person used by tests and the "try with sample data" option
    docs/           DESIGN.md, CONTRACTS.md, RUNBOOK.md, openapi.json, schemas/
    design/         ui-preview.html
