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
6. **After each chapter pipeline run**, a `notify_new_chapters` block queries for newly ingested chapters belonging to manga in `raw.user_follows` and sends a Discord notification for each.
7. **`load_mangadex_follows`** syncs the authenticated user's MangaDex follows and personal ratings into `raw.user_follows`. **`load_mangadex_statistics`** fetches community ratings, follows counts, and comment counts for all manga into `raw.manga_statistics`. **`compile_core_models`** joins both into `core.manga`, a reporting-ready table for Metabase.

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

**`raw.user_follows`**

Manga the authenticated user follows on MangaDex. Populated by the `load_mangadex_follows` pipeline, which also syncs personal ratings.

| Column | Type | Description |
|---|---|---|
| `mangadex_id` | TEXT (PK) | MangaDex UUID, matching `staging.stg_manga.mangadex_id` |
| `title` | TEXT | Human-readable title — stored here so notifications don't require a join |
| `followed_at` | TIMESTAMPTZ | When the row was first inserted (set by DB default, never overwritten on re-sync) |
| `rating` | INTEGER | User's personal rating (1–10). NULL if the title hasn't been rated. |
| `rated_at` | TIMESTAMPTZ | When the rating was first created on MangaDex. NULL if unrated. |

**`raw.manga_statistics`**

Community statistics for all manga, fetched from the public `GET /statistics/manga` endpoint. One row per manga, upserted on every `load_mangadex_statistics` run.

| Column | Type | Description |
|---|---|---|
| `mangadex_id` | TEXT (PK) | MangaDex UUID |
| `payload` | JSONB | Raw stats object: `rating` (average, bayesian, distribution), `follows`, `comments` |
| `pulled_at` | TIMESTAMPTZ | When this record was last fetched |

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

**`staging.stg_manga_statistics`**

Community statistics extracted from `raw.manga_statistics`. One row per manga, merged on each `load_mangadex_statistics` run.

| Column | Type | Notes |
|---|---|---|
| `mangadex_id` | TEXT | Primary key |
| `rating_average` | NUMERIC(5,2) | Mean of all user ratings (1–10) |
| `rating_bayesian` | NUMERIC(5,2) | Bayesian-weighted rating — more stable for titles with few ratings |
| `rating_distribution` | JSONB | Count of ratings per score, keys `"1"`–`"10"` |
| `follows` | INTEGER | Number of MangaDex users following this title |
| `comments_count` | INTEGER | Total reply count across all comment threads |
| `pulled_at` | TIMESTAMPTZ | When this row's source statistics were fetched |

### `core` schema — reporting layer

Produced by dbt. Joins staging tables into a single reporting-ready table for Metabase. Run the `compile_core_models` pipeline to refresh.

**`core.manga`**

Joins `stg_manga`, `stg_manga_statistics`, and `raw.user_follows`. One row per manga. Statistics and follow columns are `NULL` until the corresponding pipelines have run.

| Column | Type | Notes |
|---|---|---|
| `mangadex_id` | TEXT | Primary key |
| `title`, `status`, `year`, `tags`, `authors`, … | — | All columns from `stg_manga` |
| `rating_average` | NUMERIC | Community mean rating |
| `rating_bayesian` | NUMERIC | Community Bayesian rating |
| `rating_distribution` | JSONB | Per-score count |
| `follows` | INTEGER | Community follow count |
| `comments_count` | INTEGER | |
| `statistics_pulled_at` | TIMESTAMPTZ | When the stats were last refreshed |
| `user_rating` | INTEGER | Your personal rating (1–10). NULL if unrated. |
| `user_rated_at` | TIMESTAMPTZ | When you first rated the title. NULL if unrated. |
| `user_followed_at` | TIMESTAMPTZ | When the follow was synced. NULL if not followed. |
| `is_followed` | BOOLEAN | TRUE when you follow this title |

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
| `V6__create_user_follows.sql` | Creates `raw.user_follows` for follow-based chapter notifications |
| `V7__add_rating_to_user_follows.sql` | Adds `rating INTEGER` and `rated_at TIMESTAMPTZ` to `raw.user_follows` |
| `V8__create_manga_statistics.sql` | Creates `raw.manga_statistics` for community ratings and follow counts |

To add a migration, create a new file with the next version number:

```bash
touch manga_tracker/utils/migrations/V9__my_change.sql
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

**After each run**, the `notify_new_chapters` custom block fires. It queries `staging.stg_chapters` joined against `raw.user_follows` for rows with `ingested_at` newer than its own watermark, sends one Discord message per manga (grouping multiple chapters), then advances its watermark. On the very first run it only sets the watermark — no notifications are sent — so historical chapters don't flood the feed.

**Pipeline variables:**

| Variable | Description |
|---|---|
| `chapters_since_date` | Optional ISO date string. Overrides checkpoint and epoch. Use to force a re-load from a specific date. |
| `max_records` | Optional int. Caps total records fetched. Useful for development test runs. |
| `exporter_config_profile` | `io_config.yaml` profile for the Postgres connection. Default: `manga_tracker_postgres`. |

### `load_mangadex_manga`

Same pattern as `load_mangadex_chapters` but for manga titles. Uses 2-month date windows (manga is less frequent than chapters, so the windows don't need to be as small). ~90k manga total.

**After each run**, the `notify_new_manga` custom block fires. It queries `staging.stg_manga` for rows with `ingested_at` newer than its watermark whose `tags` overlap with the `notification_tags` pipeline variable, and sends one Discord message per matching manga. Configure the tags you care about directly in the pipeline variables.

**Pipeline variables:**

| Variable | Description |
|---|---|
| `manga_since_date` | Optional ISO date override. |
| `max_records` | Optional cap for dev runs. |
| `exporter_config_profile` | Postgres connection profile. |
| `notification_tags` | List of tags to match (e.g. `["Action", "Fantasy"]`). Notifications are skipped if empty. |

### `load_mangadex_follows`

Authenticates with the MangaDex API using a Personal API Client and syncs the authenticated user's followed manga and personal ratings into `raw.user_follows`. Run this once to populate your follows list, then re-run whenever you follow or rate something new on MangaDex.

**How it works:**

1. Exchanges `MANGADEX_CLIENT_ID`, `MANGADEX_CLIENT_SECRET`, `MANGADEX_USERNAME`, and `MANGADEX_PASSWORD` for a short-lived Bearer token via the MangaDex OAuth endpoint.
2. Paginates through `GET /user/follows/manga` (100 per page) to collect every followed manga.
3. Fetches personal ratings from `GET /rating` for all followed manga IDs (batched 100 at a time).
4. Upserts into `raw.user_follows` on `mangadex_id` — re-running is safe and won't reset `followed_at` timestamps. Ratings are updated on every sync.

**Setup:**

Create a Personal API Client at **mangadex.org → (avatar) → Account Settings → API Clients**, then set in `.env`:

```
MANGADEX_CLIENT_ID=personal-client-...
MANGADEX_CLIENT_SECRET=...
MANGADEX_USERNAME=your_username
MANGADEX_PASSWORD=your_password
```

**Pipeline variables:**

| Variable | Description |
|---|---|
| `exporter_config_profile` | Postgres connection profile. Default: `manga_tracker_postgres`. |

### `load_mangadex_statistics`

Fetches community statistics for all manga in `raw.manga_responses` from the public MangaDex `GET /statistics/manga` endpoint and upserts them into `raw.manga_statistics`. No authentication required.

**How it works:**

- Reads all `mangadex_id` values from `raw.manga_responses` in a single query (~90k IDs).
- Batches them 100 at a time and calls `GET /statistics/manga` for each batch, writing results to Postgres immediately after each batch. Memory usage stays flat regardless of total manga count.
- Each run is a full refresh — statistics are always current as of the last pipeline execution.
- After loading, runs `stg_manga_statistics` dbt model to clean and type-cast the raw payload.

**Runtime:** ~7–8 minutes for 90k manga (900 batches × 0.5s sleep + API call time).

**Pipeline variables:**

| Variable | Description |
|---|---|
| `exporter_config_profile` | Postgres connection profile. Default: `manga_tracker_postgres`. |

### `compile_core_models`

Runs the `core/manga` dbt model, which joins `stg_manga`, `stg_manga_statistics`, and `raw.user_follows` into a single reporting-ready table for Metabase.

Run this pipeline after any combination of the upstream pipelines have completed. Because `core.manga` depends on data from multiple pipelines with different schedules, it is intentionally decoupled from all of them.

```
load_mangadex_manga       → staging.stg_manga
load_mangadex_statistics  → staging.stg_manga_statistics   ──▶  compile_core_models → core.manga
load_mangadex_follows     → raw.user_follows
```

Statistics and follow/rating columns in `core.manga` are `NULL` for manga whose corresponding pipelines haven't run yet. This is expected — the `LEFT JOIN` design means new manga from `stg_manga` always appear immediately.

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

## Discord notifications

Both `load_mangadex_chapters` and `load_mangadex_manga` fire a Discord notification block after their dbt run. Each pipeline has its own webhook URL (separate Discord channels) and its own watermark in `mage.pipeline_checkpoints` — so the two notification streams are fully independent.

The shared watermark pattern (`utils/notifiers/base.py`) works the same in both: on the very first run the watermark is set to now without sending anything, so backfilled history never floods the feed.

Both notifiers use Discord's rich embed format: a clickable title, manga cover art as a thumbnail, and linked text in the description. Embeds are sent via `utils/notifiers/discord.py → send_embed()`.

### New chapters (followed manga)

`notify_new_chapters` runs after `stg_chapters`. It queries `staging.stg_chapters JOIN raw.user_follows JOIN staging.stg_manga` for rows ingested since the last run and sends one embed per manga, grouping multiple chapters together.

```
load_mangadex_chapters → stg_chapters (dbt) → notify_new_chapters
  ├─ Query new chapters for followed manga since watermark (+ cover_url from stg_manga)
  ├─ POST one Discord embed per manga (chapters grouped, each chapter a clickable link)
  └─ Advance watermark
```

**Required env var:** `DISCORD_CHAPTERS_WEBHOOK_URL`

**Embed format:**
- **Title** — "New chapter: Berserk" — links directly to the chapter reader (or to the manga page when multiple chapters)
- **Thumbnail** — manga cover art
- **Description** — one line per chapter, each a clickable link to `mangadex.org/chapter/{id}`

### New manga (tag filter)

`notify_new_manga` runs after `stg_manga`. It queries `staging.stg_manga` for rows ingested since the last run whose `tags` overlap with the `notification_tags` pipeline variable, and sends one embed per match.

```
load_mangadex_manga → stg_manga (dbt) → notify_new_manga
  ├─ Query new manga matching notification_tags since watermark
  ├─ POST one Discord embed per manga
  └─ Advance watermark
```

**Required env var:** `DISCORD_MANGA_WEBHOOK_URL`

Set `notification_tags` in `load_mangadex_manga/metadata.yaml`:
```yaml
notification_tags:
  - Action
  - Fantasy
```

**Embed format:**
- **Title** — "New manga: Some Title" — links to `mangadex.org/title/{id}`
- **Thumbnail** — manga cover art
- **Description** — matching tags · status | year (e.g. `Action · Fantasy | ongoing | 2024`)

### Re-testing notifications without waiting

To re-trigger notifications against already-ingested data (e.g. to test embed formatting), backdate the watermark in Postgres and then run the notification block directly in the Mage UI:

```sql
-- Re-trigger chapter notifications
UPDATE mage.pipeline_checkpoints
SET last_pulled_at = now() - interval '2 hours'
WHERE pipeline_name = 'notify_new_chapters';

-- Re-trigger manga notifications
UPDATE mage.pipeline_checkpoints
SET last_pulled_at = now() - interval '2 hours'
WHERE pipeline_name = 'notify_new_manga';
```

Then open the pipeline in the Mage UI, click the notification block, and hit **Run block** — it runs the block in isolation without re-fetching from the API.

### Setup

**1. Create a Discord server with two channels and one webhook per channel**

1. Open Discord → **+** in the sidebar → Create My Own → For me and my friends
2. Create two text channels (e.g. `#new-chapters`, `#new-manga`)
3. For each: right-click the channel → **Edit Channel** → **Integrations** → **Webhooks** → **New Webhook** → copy URL

**2. Set the env vars**

```
DISCORD_CHAPTERS_WEBHOOK_URL=https://discord.com/api/webhooks/...
DISCORD_MANGA_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

**3. Populate `raw.user_follows`**

Run the `load_mangadex_follows` pipeline. Re-run whenever you follow something new on MangaDex.

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

## Development

### Linting

The project uses [ruff](https://docs.astral.sh/ruff/) for formatting and linting. Configuration lives in `pyproject.toml`.

```bash
# Check for violations
ruff check .

# Auto-fix all fixable violations
ruff check --fix .

# Format
ruff format .
```

Rules enabled: `E`/`W` (pycodestyle), `F` (pyflakes — undefined names, unused imports), `I` (isort). Line length is 100. The `manga_tracker/dbt/` directory is excluded.

### Pre-commit hooks

Ruff runs automatically before every commit via pre-commit. To set it up locally:

```bash
pip install pre-commit
pre-commit install
```

After that, every `git commit` automatically formats and lints the staged files. If ruff makes changes, the commit is aborted — stage the fixes and commit again.

### CI

Both workflows run on every PR and on every push to `main`.

**`.github/workflows/lint.yml` — `Lint`**

Runs `ruff format --check` and `ruff check` without `--fix`. If violations exist the workflow fails and the author must fix them locally before merging.

**`.github/workflows/docker_build.yml` — `Docker build`**

Builds both `mage.Dockerfile` and `api.Dockerfile` to catch broken images before they reach deployment.

**`.github/workflows/pip_audit.yml` — `Dependency audit`**

Runs `pip-audit` against `requirements.txt` and `requirements-api.txt` to flag packages with known CVEs.

**`.github/workflows/migrations_and_dbt.yml` — `Migrations & dbt`**

Two separate jobs:

| Job | What it does |
|---|---|
| `flyway migrations` | Spins up a fresh `postgres:17` container, runs all Flyway migrations, then runs `flyway validate` to verify that no applied migration file has been edited after the fact (checksum check). |
| `dbt run & test` | Depends on `flyway migrations`. Spins up its own fresh Postgres, re-runs migrations to set up the schema, then runs `dbt run --empty` to execute all staging models against the real schema (catches missing columns, bad joins, and SQL errors that `compile` alone misses), followed by `dbt test` to run all schema tests. |

The dbt job only runs if Flyway passes — no point running models against a broken schema.

---

## Project structure

```
manga-tracker/
├── .github/
│   ├── dependabot.yml                  # Weekly auto-PRs for pip + GitHub Actions version bumps
│   └── workflows/
│       ├── docker_build.yml            # Builds mage + api Docker images on every PR and push to main
│       ├── lint.yml                    # Ruff lint + format check on every PR and push to main
│       ├── migrations_and_dbt.yml      # Flyway migrations + dbt run & test on every PR and push to main
│       └── pip_audit.yml               # pip-audit CVE scan on every PR and push to main
├── .pre-commit-config.yaml        # Ruff pre-commit hooks
├── pyproject.toml                 # Ruff configuration
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
│   ├── custom/
│   │   ├── notify_new_chapters.py        # Fires Discord notifications after stg_chapters dbt run
│   │   └── notify_new_manga.py           # Fires Discord notifications after stg_manga dbt run
│   ├── data_loaders/
│   │   ├── load_and_export_chapters.py   # Streams + exports chapters, checkpoints
│   │   ├── load_and_export_manga.py      # Streams + exports manga, checkpoints
│   │   ├── load_and_export_statistics.py # Streams + exports community statistics in batches
│   │   ├── load_data_from_postgres.py    # Generic Postgres loader block
│   │   └── lookup_follows.py             # Fetches user follows + ratings from MangaDex API
│   ├── data_exporters/
│   │   └── export_data_to_postgres.py    # Generic Postgres exporter block
│   ├── utils/
│   │   ├── loaders/
│   │   │   ├── mangadex/
│   │   │   │   ├── chapters.py    # MangaDex chapter streaming logic
│   │   │   │   ├── follows.py     # MangaDex authenticated follows + ratings loader
│   │   │   │   ├── manga.py       # MangaDex manga streaming logic
│   │   │   │   └── statistics.py  # MangaDex community statistics batch loader
│   │   │   └── postgres/
│   │   │       └── loader.py      # Shared Postgres read utility
│   │   ├── exporters/
│   │   │   └── postgres/
│   │   │       └── exporter.py    # Shared Postgres write utility
│   │   ├── helpers/
│   │   │   ├── api_request.py     # HTTP request helper with retry logic
│   │   │   └── checkpoint.py      # Shared read/write helpers for mage.pipeline_checkpoints
│   │   ├── notifiers/
│   │   │   ├── base.py              # Shared run_with_watermark wrapper used by all notifiers
│   │   │   ├── chapter_notifier.py  # Queries new chapters + dispatches Discord notifications
│   │   │   ├── manga_notifier.py    # Queries new tag-matched manga + dispatches Discord notifications
│   │   │   └── discord.py           # Discord incoming webhook helper
│   │   ├── migrations/            # Flyway SQL migration files
│   │   │   ├── V1__create_schemas.sql
│   │   │   ├── V2__create_metabase_db.sql
│   │   │   ├── V3__init_raw_api_response_tables.sql
│   │   │   ├── V4__init_mage_pipeline_checkpoints.sql
│   │   │   ├── V5__create_audit_schema.sql
│   │   │   ├── V6__create_user_follows.sql
│   │   │   ├── V7__add_rating_to_user_follows.sql
│   │   │   └── V8__create_manga_statistics.sql
│   │   └── sql/
│   │       └── postgres/
│   │           └── get_checkpoint.sql
│   ├── dbt/
│   │   └── manga_tracker_dbt/
│   │       └── models/
│   │           ├── staging/
│   │           │   ├── stg_manga.sql
│   │           │   ├── stg_chapters.sql
│   │           │   └── stg_manga_statistics.sql
│   │           └── core/
│   │               └── manga.sql
│   └── pipelines/
│       ├── compile_core_models/
│       │   └── metadata.yaml
│       ├── load_mangadex_chapters/
│       │   └── metadata.yaml
│       ├── load_mangadex_follows/
│       │   └── metadata.yaml
│       ├── load_mangadex_manga/
│       │   └── metadata.yaml
│       └── load_mangadex_statistics/
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
