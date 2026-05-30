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
│  └────────┘            │                  │   ┌──────────┐    ┌───────┐ │
│                        │                  │──▶│   api    │──▶│ redis │ │
│                        │   metabase db    │   │ FastAPI  │◀──│       │ │
│                        │                  │   └──────────┘    └───────┘ │
│                        └──────────────────┘        │ :8000             │
│                                │                                        │
│                                ▼                                        │
│                         ┌──────────┐                                    │
│                         │ metabase │─────────────────────────────────▶ :3000
│                         └──────────┘                                    │
└─────────────────────────────────────────────────────────────────────────┘
```

**Data flow:**

1. **Mage** pipelines stream chapters and manga from the MangaDex API and upsert them into `raw.chapter_responses` and `raw.manga_responses` as JSONB payloads.
2. **dbt** transforms the raw JSONB into clean, typed columns in `staging.stg_manga` and `staging.stg_chapters`.
3. **The FastAPI service** queries the staging schema and serves the data over HTTP. Every request is logged to `audit.api_requests`.
4. **Metabase** connects to the same staging schema for dashboards and exploration.
5. **Postgres** logs every SQL statement it receives — from any client (TablePlus, Mage, dbt, Metabase, psql) — with full duration and connection context.

---

## Services

| Service | Port | Purpose |
|---|---|---|
| `postgres` | 5432 | Main database. Hosts `manga_tracker` (app data) and `metabase` (Metabase internals). |
| `mage` | 6789 | Pipeline orchestrator. Runs the data loaders that fetch from MangaDex. |
| `flyway` | — | Runs SQL migrations on startup. Exits once done. |
| `redis` | 6379 | In-memory cache for API responses. |
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

### `audit` schema — observability

**`audit.api_requests`**

Every HTTP request the FastAPI service handles is written here by the `AuditMiddleware`. The write is fire-and-forget — a failure to write never surfaces as an API error.

| Column | Type | Description |
|---|---|---|
| `id` | BIGSERIAL | Surrogate key |
| `request_id` | UUID | Unique per request; also returned in the `X-Request-Id` response header |
| `ts` | TIMESTAMPTZ | When the request was received |
| `method` | TEXT | `GET`, `POST`, etc. |
| `path` | TEXT | URL path, e.g. `/manga/abc123/chapters` |
| `query_string` | TEXT | Raw query string, e.g. `limit=50&offset=100` |
| `status_code` | INT | HTTP status of the response |
| `duration_ms` | FLOAT | End-to-end request duration in milliseconds (includes DB + cache time) |
| `client_ip` | TEXT | IP address of the caller |
| `user_agent` | TEXT | `User-Agent` header |

Indexed on `ts DESC` and `path` for the most common queries (recency lookup, per-endpoint analysis).

---

## Migrations

Migration files live in `manga_tracker/utils/migrations/` and use standard Flyway versioned SQL naming (`V{n}__{description}.sql`). Flyway runs them in version order on startup and tracks applied migrations in `flyway_schema_history`.

| File | What it does |
|---|---|
| `V1__create_schemas.sql` | Creates `raw`, `staging`, `core`, `mage` schemas |
| `V2__create_metabase_db.sql` | Creates the `metabase` database (non-transactional — `CREATE DATABASE` can't run inside a Postgres transaction) |
| `V3__init_raw_api_response_tables.sql` | Creates `raw.manga_responses` and `raw.chapter_responses` with indexes |
| `V4__init_mage_pipeline_checkpoints.sql` | Creates `mage.pipeline_checkpoints` |
| `V5__create_audit_schema.sql` | Creates `audit` schema, enables `pg_stat_statements` extension, creates `audit.api_requests` with indexes |

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

## Response caching (Redis)

All API list endpoints cache their responses in Redis so repeated requests with the same parameters don't hit Postgres.

**How it works:**

```
Request arrives
      │
      ▼
Check Redis for cache_key
      │
  ┌───┴────────────────┐
  │ HIT                │ MISS
  │                    ▼
  │           Query Postgres
  │                    │
  │           Store result in Redis
  │           with TTL
  └───────────────┐    │
                  ▼    ▼
              Return response
```

**Cache keys and TTLs:**

| Endpoint | Cache key | TTL |
|---|---|---|
| `GET /manga` | `manga:list:{status}:{tag}:{content_rating}:{limit}:{offset}` | 1 hour |
| `GET /manga/{id}` | `manga:{mangadex_id}` | 24 hours |
| `GET /manga/{id}/chapters` | `manga:{mangadex_id}:chapters:{limit}:{offset}` | 1 hour |
| `GET /chapters/recent` | `chapters:recent:{limit}:{offset}` | 10 minutes |

Every unique combination of query parameters gets its own cache entry, so `GET /manga?status=ongoing` and `GET /manga?status=completed` are cached independently.

**TTL rationale:** The data only changes when a Mage pipeline run finishes. Pipelines run at most hourly, so a 1-hour TTL means the cache is always fresh relative to what's in the database. Individual manga metadata (`GET /manga/{id}`) rarely changes at all, so 24 hours is safe. Recent chapters use a shorter 10-minute TTL since new uploads appear more frequently.

**Fail-open design:** If Redis is unavailable (e.g. the container is restarting), the API silently skips the cache and queries Postgres directly. No errors are surfaced to the caller. The cache is an optimization, not a dependency.

**Interacting with Redis:**

Connect to the Redis CLI inside the running container:

```bash
docker-compose exec redis redis-cli
```

You're now in an interactive shell connected to the cache:

```
127.0.0.1:6379> KEYS *
127.0.0.1:6379> GET "chapters:recent:20:0"
127.0.0.1:6379> TTL "manga:list:None:None:None:20:0"
127.0.0.1:6379> FLUSHALL
127.0.0.1:6379> exit
```

Or run a single command without entering the shell:

```bash
docker-compose exec redis redis-cli KEYS "*"
docker-compose exec redis redis-cli FLUSHALL
```

Useful commands:

| Command | What it does |
|---|---|
| `KEYS *` | List every cached key |
| `GET <key>` | Show the stored JSON for a key |
| `TTL <key>` | Seconds until the key expires (`-2` means the key doesn't exist) |
| `DEL <key>` | Delete one key — forces a cache miss on the next request |
| `FLUSHALL` | Wipe everything |
| `DBSIZE` | How many keys are currently stored |

## Auditing

The system has two layers of auditing that work independently: one at the API layer and one at the database layer. Together they let you answer questions like "which endpoint is slowest?", "who ran a full table scan?", "how many requests came in between 2–3pm?", and "did Metabase run a particularly expensive query?"

### Layer 1: API request auditing

`AuditMiddleware` in `manga_tracker/api/middleware.py` wraps every request. It:

1. Records the start time before calling the route handler
2. Lets the response complete normally
3. Calculates total duration (including DB queries and cache lookups)
4. Writes one row to `audit.api_requests` — asynchronously, in a separate DB session
5. Attaches an `X-Request-Id` UUID to the response header

The write is wrapped in a bare `except` block so a database blip never causes a request to fail. The audit is best-effort.

**Querying API audit data:**

```sql
-- Request volume by endpoint over the last 24 hours
SELECT path, COUNT(*) AS requests
FROM audit.api_requests
WHERE ts > now() - interval '24 hours'
GROUP BY path
ORDER BY requests DESC;

-- P50 / P95 / P99 latency per endpoint
SELECT
    path,
    ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY duration_ms)::numeric, 1) AS p50_ms,
    ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms)::numeric, 1) AS p95_ms,
    ROUND(PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY duration_ms)::numeric, 1) AS p99_ms,
    COUNT(*) AS calls
FROM audit.api_requests
GROUP BY path
ORDER BY p95_ms DESC;

-- Error rate (any 4xx or 5xx)
SELECT
    path,
    COUNT(*) FILTER (WHERE status_code >= 400) AS errors,
    COUNT(*) AS total,
    ROUND(100.0 * COUNT(*) FILTER (WHERE status_code >= 400) / COUNT(*), 1) AS error_pct
FROM audit.api_requests
GROUP BY path
ORDER BY error_pct DESC;

-- Trace a specific request by ID (the ID is in the X-Request-Id response header)
SELECT * FROM audit.api_requests WHERE request_id = '<uuid>';
```

You can also build all of these as Metabase questions by connecting to the `audit` schema.

### Layer 2: Postgres query auditing

The Postgres container is configured to log every statement it receives, regardless of the client. This catches queries from TablePlus, Mage pipeline runs, dbt model executions, Metabase dashboard loads, and direct `psql` sessions.

**What's enabled (set via `command:` in docker-compose):**

| Setting | Value | Effect |
|---|---|---|
| `shared_preload_libraries` | `pg_stat_statements` | Loads the query stats extension at startup |
| `pg_stat_statements.track` | `all` | Tracks queries from all sources, including nested function calls |
| `log_statement` | `all` | Logs the text of every statement to the Postgres log |
| `log_duration` | `on` | Appends execution time to each log line |
| `log_min_duration_statement` | `0` | Logs duration for every statement (not just slow ones) |
| `log_line_prefix` | `'%t [%p] user=%u db=%d app=%a client=%h '` | Prefixes each log line with timestamp, PID, username, database, application name, and client host |

The `app=%a` field in the prefix is the `application_name` connection parameter, which is set automatically by most clients:
- **dbt**: sets `application_name` to something like `dbt`
- **Metabase**: sets it to `Metabase`
- **TablePlus**: sets it to `TablePlus` (or configurable)
- **psql**: defaults to `psql`
- **FastAPI/asyncpg**: defaults to the process name

This lets you distinguish which system issued a query even when multiple clients are connected simultaneously.

**Viewing Postgres logs:**

```bash
# Stream logs in real time
docker-compose logs -f postgres

# Filter for slow queries (> 1 second)
docker-compose logs postgres | grep "duration: [0-9]\{4,\}"

# Show only queries from Metabase
docker-compose logs postgres | grep "app=Metabase"

# Show only queries from dbt
docker-compose logs postgres | grep "app=dbt"
```

**Querying the `pg_stat_statements` view:**

`pg_stat_statements` accumulates statistics for every unique query fingerprint (parameters are normalized to `$1`, `$2`, etc.), so you can find expensive query patterns without sifting through logs.

```sql
-- Top 10 most time-consuming query shapes
SELECT
    query,
    calls,
    ROUND(total_exec_time::numeric, 2) AS total_ms,
    ROUND(mean_exec_time::numeric, 2) AS mean_ms,
    rows
FROM pg_stat_statements
WHERE query NOT LIKE '%pg_stat_statements%'
ORDER BY total_exec_time DESC
LIMIT 10;

-- Queries with the worst cache hit ratio (high blks_read = lots of disk I/O)
SELECT
    query,
    calls,
    shared_blks_hit,
    shared_blks_read,
    ROUND(100.0 * shared_blks_hit / NULLIF(shared_blks_hit + shared_blks_read, 0), 1) AS cache_hit_pct
FROM pg_stat_statements
ORDER BY shared_blks_read DESC
LIMIT 10;

-- Reset stats (useful after a schema change or optimization)
SELECT pg_stat_statements_reset();
```

Note: `pg_stat_statements` resets when the Postgres container restarts. It reflects the current container lifetime only.

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

### Fetching all records (full pagination)

Every list endpoint returns a `total` field. Use it to loop through all pages until you've collected everything. The maximum page size is 100.

```python
import httpx

def get_all_manga(base_url="http://localhost:8000"):
    all_manga = []
    limit = 100
    offset = 0

    while True:
        response = httpx.get(f"{base_url}/manga", params={"limit": limit, "offset": offset})
        response.raise_for_status()
        data = response.json()

        all_manga.extend(data["data"])

        if offset + limit >= data["total"]:
            break

        offset += limit

    return all_manga
```

The same pattern works for any list endpoint — swap the URL and adjust the params:

```python
# All chapters for a specific manga
def get_all_chapters(mangadex_id, base_url="http://localhost:8000"):
    all_chapters = []
    limit = 100
    offset = 0

    while True:
        response = httpx.get(
            f"{base_url}/manga/{mangadex_id}/chapters",
            params={"limit": limit, "offset": offset},
        )
        response.raise_for_status()
        data = response.json()

        all_chapters.extend(data["data"])

        if offset + limit >= data["total"]:
            break

        offset += limit

    return all_chapters
```

> **Note:** With 90k manga at 100 per page that's 900 HTTP requests. If you need the full dataset in one shot, querying `staging.stg_manga` directly in Postgres is faster. The API pagination is designed for consumers that only need a slice at a time.

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
│   │   ├── main.py                # App entry point, router + middleware registration
│   │   ├── database.py            # Async SQLAlchemy engine + get_db() dependency
│   │   ├── models.py              # Pydantic response models
│   │   ├── cache.py               # Redis get/set helpers + TTL constants
│   │   ├── middleware.py          # AuditMiddleware — logs every request to audit.api_requests
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
│   │   │   ├── V4__init_mage_pipeline_checkpoints.sql
│   │   │   └── V5__create_audit_schema.sql
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
