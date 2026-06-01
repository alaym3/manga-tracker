# Contributing

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- Python 3.10+ (for linting tools — not needed to run the stack)
- Git

## Local Python environment

The stack runs entirely in Docker, but you need a local Python environment for the linting tools and pre-commit hooks.

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install ruff sqlfluff pre-commit
```

Set up the pre-commit hook so ruff runs automatically before every commit:

```bash
pre-commit install
```

After that, `git commit` will auto-format and lint staged files. If ruff makes changes, the commit is aborted — stage the fixes and commit again.

## Setup

**1. Clone and create your `.env`**

```bash
git clone https://github.com/alaym3/manga-tracker.git
cd manga-tracker
cp .env.example .env
```

The defaults in `.env.example` work for local development. The only values you need to fill in are for optional features:

| Variable | Required for |
|---|---|
| `MANGADEX_CLIENT_ID/SECRET/USERNAME/PASSWORD` | `load_mangadex_follows` pipeline (syncing your personal follows) |
| `DISCORD_CHAPTERS_WEBHOOK_URL` | Chapter Discord notifications |
| `DISCORD_MANGA_WEBHOOK_URL` | New manga Discord notifications |

**2. Start the stack**

```bash
docker compose up --build
```

Flyway runs all database migrations automatically on startup. First boot takes a few minutes as images download.

## Services

| Service | URL | What it is |
|---|---|---|
| Mage | http://localhost:6789 | Pipeline UI — run data loaders here |
| API | http://localhost:8000 | FastAPI REST API ([Swagger docs](http://localhost:8000/docs)) |
| Metabase | http://localhost:3000 | BI dashboard |
| Postgres | `localhost:5432` | Connect with any SQL client (user: `postgres`, pass: `postgres`, db: `manga_tracker`) |

## Common commands

```bash
# Follow logs for a specific service
docker compose logs -f api
docker compose logs -f mage

# Rebuild and restart one service after a code change
docker compose up --build api

# Wipe everything and start fresh (drops all data)
docker compose down -v && docker compose up --build

# Lint
ruff check .
ruff format .
```

## Making changes

- **Python linting:** ruff handles formatting and linting. Run `ruff check .` before pushing — CI will fail if there are violations.
- **SQL linting:** Use `sqlfluff lint` on any new or modified SQL files (migrations, dbt models).
- **Database migrations:** Add a new file to `manga_tracker/utils/migrations/` using the next version number (`V9__my_change.sql`). Flyway picks it up on the next `docker compose up`.
- **CI:** All checks (lint, docker build, migrations + dbt, dependency audit) run automatically on every PR.

See the [README](README.md) for full documentation on pipelines, the API, the database schema, and auditing.
