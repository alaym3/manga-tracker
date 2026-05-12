# manga-tracker

## Running services

This repository defines the following services in docker-compose.yml:

- **mage** — your Mage project runtime
- **postgres** — the Postgres database used by Mage and Metabase
- **metabase** — the Metabase analytics dashboard
- **flyway** — Flyway SQL migrations for Postgres

## Accessing services

- **Mage UI**: http://localhost:6789
- **Metabase**: http://localhost:3000
- **Postgres**: connect with TablePlus, DBeaver, psql, or another database client using localhost:5432

## Accessing Postgres database

You can connect to the Postgres database using any SQL client that supports PostgreSQL, for example:

- **TablePlus**: connect using host `localhost`, port `5432`, database `manga_tracker`, username `postgres`, password `postgres`.

## Start all services

```bash
docker compose up -d
```

This starts mage, postgres, and metabase in the background.

## Start only Postgres

```bash
docker compose up -d postgres
```

Use this when you want the database available without starting Mage or Metabase.

## Start only Mage

```bash
docker compose up -d mage
```

This starts the Mage project runtime. The mage service depends on the postgres service, so postgres will be started automatically if needed.

## Start only Metabase

```bash
docker compose up -d metabase
```

This starts the Metabase dashboard and connects it to the postgres database.

## Postgres migrations service

This repo now includes a Flyway-based migration service.

Migration files live in `manga_tracker/utils/migrations/` and use Flyway SQL syntax.

Example migrations:

- `manga_tracker/utils/migrations/V1__create_schemas.sql`
- `manga_tracker/utils/migrations/V2__init_raw_api_response_tables.sql`
- `manga_tracker/utils/migrations/V3__init_mage_pipeline_checkpoints.sql`

Each migration file contains the SQL to apply the migration. Flyway handles versioning automatically based on the file names.

Usage:

```bash
docker compose run --rm flyway info
docker compose run --rm flyway migrate
docker compose run --rm flyway validate
```

To create a new migration, create a new SQL file in `manga_tracker/utils/migrations/` with the format `V{version}__{description}.sql`, where version is the next number in sequence.

## Manga Loader

The manga loader is a data loader component that fetches manga data from the MangaDex API. It streams raw manga responses, allowing for efficient handling of large datasets. The loader returns a pandas DataFrame containing the manga ID, the timestamp when the data was pulled, and the full API response payload. This data can be configured with parameters such as the number of records to fetch (limit) and what related data to include (includes). The loader is integrated into the Mage pipeline for automated data ingestion and processing.