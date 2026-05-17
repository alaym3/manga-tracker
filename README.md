# manga-tracker

A personal data pipeline and REST API for tracking manga from [MangaDex](https://mangadex.org). Ingests raw API data, transforms it with dbt, and exposes it over HTTP.

---

## Architecture

```
MangaDex API
     │
     ▼
┌─────────────────────────────────────────────────────────────┐
│                     docker-compose network                   │
│                                                             │
│  ┌────────┐   raw.*    ┌──────────────────┐   staging.*    │
│  │  mage  │──────────▶│    postgres 17    │──────────────▶ │
│  │        │            │   manga_tracker  │                │
│  └────────┘            │                  │   ┌──────────┐ │
│                        │                  │◀──│   dbt    │ │
│  ┌────────┐            │                  │   └──────────┘ │
│  │ flyway │──migrate──▶│                  │                │
│  └────────┘            │                  │   ┌──────────┐ │
│                        │                  │──▶│   api    │──▶ :8000
│                        │   metabase db    │   │ FastAPI  │ │
│                        │                  │   └──────────┘ │
│                        └──────────────────┘                │
│                                │                           │
│                                ▼                           │
│                         ┌──────────┐                       │
│                         │ metabase │──────────────────────▶ :3000
│                         └──────────┘                       │
└─────────────────────────────────────────────────────────────┘
```

**Data flow:**

1. **Mage** pipelines stream chapters and manga from the MangaDex API and upsert them into `raw.chapter_responses` and `raw.manga_responses` as JSONB payloads.
2. **dbt** transforms the raw JSONB into clean, typed columns in `staging.stg_manga` and `staging.stg_chapters`.
3. **The FastAPI service** queries the staging schema and serves the data over HTTP.
4. **Metabase** connects to the same staging schema for dashboards and exploration.

---

## Services

| Service | Port | Purpose |
|---|---|---|
| `postgres` | 5432 | Main database. Hosts `manga_tracker` (app data) and `metabase` (Metabase internals). |
| `mage` | 6789 | Pipeline orchestrator. Runs the data loaders that fetch from MangaDex. |
| `flyway` | — | Runs SQL migrations on startup. Exits once done. |
| `api` | 8000 | FastAPI REST API over the staging schema. |
| `metabase` | 3000 | BI dashboard connected to the staging schema. |

---

## Getting started

### Prerequisites

- Docker and Docker Compose
- A `.env` file in the repo root (see `.env.example` if present)

### Start everything

```bash
docker-compose up --build
```

Flyway runs migrations automatically on startup. On a fresh environment this creates all schemas and tables before Mage or the API start accepting traffic.

### Start individual services

```bash
# Database only
docker-compose up -d postgres

# Database + migrations
docker-compose up -d postgres flyway

# Full pipeline stack (no API or Metabase)
docker-compose up -d postgres flyway mage

# API only (assumes postgres is already running)
docker-compose up --build api
```

### Wipe and recreate the database

```bash
docker-compose down -v && docker-compose up --build
```

The `-v` flag removes the `postgres_data` named volume so Postgres starts completely fresh and Flyway re-runs all migrations from V1.

---

## Database schema

### `raw` schema — landing zone

Append-only tables that store the full MangaDex API response payload as JSONB. These are never modified after insert. Mage upserts on `mangadex_id`.

**`raw.manga_responses`**

| Column | Type | Description |
|---|---|---|
| `id` | SERIAL | Internal surrogate key |
| `mangadex_id` | TEXT UNIQUE | MangaDex UUID |
| `pulled_at` | TIMESTAMPTZ | When this record was fetched |
| `payload` | JSONB | Full `data[]` item from the API response |

**`raw.chapter_responses`**

| Column | Type | Description |
|---|---|---|
| `id` | SERIAL | Internal surrogate key |
| `mangadex_id` | TEXT UNIQUE | MangaDex UUID |
| `manga_id` | TEXT | Parent manga UUID (denormalized from relationships[]) |
| `pulled_at` | TIMESTAMPTZ | When this record was fetched |
| `payload` | JSONB | Full `data[]` item from the API response |

### `staging` schema — transformed data

Produced by dbt. These are the tables the API and Metabase query.

**`staging.stg_manga`**

| Column | Type | Notes |
|---|---|---|
| `mangadex_id` | TEXT | Primary key |
| `source` | TEXT | Always `'mangadex'` |
| `title` | TEXT | English title; falls back to romanized Japanese |
| `title_japanese` | TEXT | |
| `alt_titles` | JSONB | Array of `{language: title}` objects |
| `description` | TEXT | English description; falls back to Japanese |
| `original_language` | TEXT | e.g. `ja`, `ko`, `zh` |
| `status` | TEXT | `ongoing` \| `completed` \| `hiatus` \| `cancelled` |
| `year` | INT | Year of first publication |
| `content_rating` | TEXT | `safe` \| `suggestive` \| `erotica` |
| `tags` | TEXT[] | e.g. `['Action', 'Romance', 'Fantasy']` |
| `authors` | TEXT[] | |
| `artists` | TEXT[] | |
| `cover_url` | TEXT | Full URL to cover image |
| `created_at_source` | TIMESTAMPTZ | |
| `updated_at_source` | TIMESTAMPTZ | |
| `ingested_at` | TIMESTAMPTZ | When dbt last wrote this row |

**`staging.stg_chapters`**

| Column | Type | Notes |
|---|---|---|
| `mangadex_id` | TEXT | Primary key |
| `manga_mangadex_id` | TEXT | FK to `stg_manga.mangadex_id` |
| `volume` | TEXT | e.g. `"1"`, may be null |
| `chapter_number` | TEXT | e.g. `"12.5"`, `"Oneshot"` — stored as text intentionally |
| `title` | TEXT | Chapter title, may be null |
| `language` | TEXT | `en` for all records (filtered at ingest) |
| `is_unavailable` | BOOLEAN | True if the chapter has been taken down |
| `pages` | INT | |
| `scanlation_group` | TEXT | |
| `published_at` | TIMESTAMPTZ | |
| `readable_at` | TIMESTAMPTZ | |
| `external_url` | TEXT | For chapters hosted off MangaDex |
| `ingested_at` | TIMESTAMPTZ | |

### `mage` schema — pipeline metadata

**`mage.pipeline_checkpoints`**

| Column | Type | Description |
|---|---|---|
| `pipeline_name` | TEXT (PK) | e.g. `load_mangadex_chapters` |
| `last_pulled_at` | TIMESTAMPTZ | End timestamp of the last exported date chunk |
| `updated_at` | TIMESTAMPTZ | When this checkpoint was last written |

---

## Migrations

Migration files live in `manga_tracker/utils/migrations/` and use standard Flyway versioned SQL naming (`V{n}__{description}.sql`). Flyway runs them in version order on startup and tracks applied migrations in `flyway_schema_history`.

| File | What it does |
|---|---|
| `V1__create_schemas.sql` | Creates `raw`, `staging`, `core`, `mage` schemas |
| `V2__create_metabase_db.sql` | Creates the `metabase` database (non-transactional — `CREATE DATABASE` can't run inside a Postgres transaction) |
| `V3__init_raw_api_response_tables.sql` | Creates `raw.manga_responses` and `raw.chapter_responses` with indexes |
| `V4__init_mage_pipeline_checkpoints.sql` | Creates `mage.pipeline_checkpoints` |

To add a migration, create a new file with the next version number:

```bash
touch manga_tracker/utils/migrations/V5__my_change.sql
```

Flyway picks it up automatically on the next `docker-compose up`.

Useful Flyway commands:

```bash
# Show migration status
docker-compose run --rm flyway info

# Validate that applied migrations match the files on disk
docker-compose run --rm flyway validate
```

---

## Mage pipelines

Access the Mage UI at **http://localhost:6789**.

### `load_mangadex_chapters`

Fetches all English chapters from the MangaDex API and upserts them into `raw.chapter_responses`.

**How it works:**

- The API has a hard limit of 10,000 results per paginated query (Elasticsearch offset limit). To work around this, the loader chunks requests by `createdAt` date — default 7-day windows — and paginates within each window.
- If any 7-day window would exceed 10,000 results (common in recent years with high upload volume), the window is automatically split in half recursively until the chunk fits.
- After each date window is fetched and exported, the pipeline writes `chunk_end` to `mage.pipeline_checkpoints`. If the pipeline crashes or is stopped partway through, the next run reads this checkpoint and resumes from where it left off rather than starting from 2018.
- Upserts on `mangadex_id` are idempotent — re-running any date range is safe.

**For a full backfill (first run):**

Run the pipeline with no variables set. It reads the checkpoint (none exists), defaults to `_MANGADEX_EPOCH = 2018-01-01`, and works forward to the present. This takes several hours due to API rate limiting (1.5s sleep between pages).

**For incremental runs (scheduled):**

Run on a schedule (e.g. hourly). The pipeline reads the checkpoint, generates one small date window covering the interval since the last run, fetches new chapters, and finishes in seconds.

**Pipeline variables:**

| Variable | Description |
|---|---|
| `chapters_since_date` | Optional ISO date string. Overrides checkpoint and epoch. Use to force a re-load from a specific date. |
| `max_records` | Optional int. Caps total records fetched. Useful for development test runs. |
| `exporter_config_profile` | `io_config.yaml` profile for the Postgres connection. Default: `manga_tracker_postgres`. |

### `load_mangadex_manga`

Same pattern as `load_mangadex_chapters` but for manga titles. Uses 2-month date windows (manga is less frequent than chapters, so the windows don't need to be as small). ~90k manga total.

**Pipeline variables:**

| Variable | Description |
|---|---|
| `manga_since_date` | Optional ISO date override. |
| `max_records` | Optional cap for dev runs. |
| `exporter_config_profile` | Postgres connection profile. |

---

## REST API

The FastAPI service runs on **http://localhost:8000**. Interactive docs (Swagger UI) are available at **http://localhost:8000/docs**.

### Endpoints

#### `GET /health`

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

#### `GET /manga`

Paginated list of all manga with optional filters.

| Param | Type | Description |
|---|---|---|
| `status` | string | `ongoing` \| `completed` \| `hiatus` \| `cancelled` |
| `tag` | string | Filter by tag (case-sensitive, e.g. `Action`, `Romance`) |
| `content_rating` | string | `safe` \| `suggestive` \| `erotica` |
| `limit` | int | Max results (default 20, max 100) |
| `offset` | int | Rows to skip (default 0) |

```bash
curl "http://localhost:8000/manga?status=ongoing&tag=Action&limit=5" | jq .
```

```json
{
  "total": 412,
  "limit": 5,
  "offset": 0,
  "data": [
    {
      "mangadex_id": "...",
      "source": "mangadex",
      "title": "Berserk",
      "status": "ongoing",
      "year": 1989,
      "content_rating": "suggestive",
      "original_language": "ja",
      "tags": ["Action", "Adventure", "Fantasy"],
      "authors": ["Miura Kentarou"],
      "cover_url": "https://uploads.mangadex.org/covers/..."
    }
  ]
}
```

#### `GET /manga/{mangadex_id}`

Full detail for one manga including description, alt titles, and all timestamps.

```bash
curl "http://localhost:8000/manga/801513ba-a712-498c-8f57-cae55b38cc92" | jq .
```

Returns 404 if the ID is not found.

#### `GET /manga/{mangadex_id}/chapters`

All chapters for a manga, ordered chronologically by `published_at`.

```bash
curl "http://localhost:8000/manga/801513ba-a712-498c-8f57-cae55b38cc92/chapters?limit=10" | jq .
```

#### `GET /chapters/recent`

The most recently published available chapters across all manga.

```bash
curl "http://localhost:8000/chapters/recent?limit=20" | jq '.data[] | {title, published_at}'
```

### Response shapes

**`PaginatedManga`**
```json
{ "total": 90123, "limit": 20, "offset": 0, "data": [MangaSummary] }
```

**`MangaSummary`** (used in list responses — lightweight)
```
mangadex_id, source, title, status, year, content_rating,
original_language, tags[], authors[], cover_url
```

**`MangaDetail`** (used in single-item responses — full)
```
all MangaSummary fields +
title_japanese, alt_titles, description, artists[],
created_at_source, updated_at_source, ingested_at
```

**`PaginatedChapters`**
```json
{ "total": 400000, "limit": 20, "offset": 0, "data": [Chapter] }
```

**`Chapter`**
```
mangadex_id, manga_mangadex_id, volume, chapter_number, title,
language, is_unavailable, pages, scanlation_group,
published_at, readable_at, external_url
```

---

## Project structure

```
manga-tracker/
├── docker-compose.yml
├── mage.Dockerfile
├── api.Dockerfile
├── requirements.txt               # Mage pipeline dependencies
├── requirements-api.txt           # FastAPI service dependencies
├── manga_tracker/
│   ├── api/                       # FastAPI service
│   │   ├── main.py                # App entry point, router registration
│   │   ├── database.py            # Async SQLAlchemy engine + get_db() dependency
│   │   ├── models.py              # Pydantic response models
│   │   └── routers/
│   │       ├── manga.py           # /manga routes
│   │       └── chapters.py        # /chapters routes
│   ├── data_loaders/
│   │   ├── load_and_export_chapters.py   # Streams + exports chapters, checkpoints
│   │   ├── load_and_export_manga.py      # Streams + exports manga, checkpoints
│   │   └── load_data_from_postgres.py    # Generic Postgres loader block
│   ├── data_exporters/
│   │   └── export_data_to_postgres.py    # Generic Postgres exporter block
│   ├── utils/
│   │   ├── loaders/
│   │   │   ├── mangadex/
│   │   │   │   ├── chapters.py    # MangaDex chapter streaming logic
│   │   │   │   └── manga.py       # MangaDex manga streaming logic
│   │   │   └── postgres/
│   │   │       └── loader.py      # Shared Postgres read utility
│   │   ├── exporters/
│   │   │   └── postgres/
│   │   │       └── exporter.py    # Shared Postgres write utility
│   │   ├── helpers/
│   │   │   └── api_request.py     # HTTP request helper with retry logic
│   │   ├── migrations/            # Flyway SQL migration files
│   │   │   ├── V1__create_schemas.sql
│   │   │   ├── V2__create_metabase_db.sql
│   │   │   ├── V3__init_raw_api_response_tables.sql
│   │   │   └── V4__init_mage_pipeline_checkpoints.sql
│   │   └── sql/
│   │       └── postgres/
│   │           └── get_checkpoint.sql
│   ├── dbt/
│   │   └── manga_tracker_dbt/
│   │       └── models/
│   │           └── staging/
│   │               ├── stg_manga.sql
│   │               └── stg_chapters.sql
│   └── pipelines/
│       ├── load_mangadex_chapters/
│       │   └── metadata.yaml
│       └── load_mangadex_manga/
│           └── metadata.yaml
```

---

## Connecting to Postgres directly

Use any SQL client (TablePlus, DBeaver, psql) with:

| Setting | Value |
|---|---|
| Host | `localhost` |
| Port | `5432` |
| Database | `manga_tracker` |
| Username | `postgres` |
| Password | `postgres` |

```bash
# psql
psql -h localhost -U postgres -d manga_tracker
```
