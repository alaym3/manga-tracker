CREATE SCHEMA IF NOT EXISTS audit;

CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

CREATE TABLE audit.api_requests (
    id             BIGSERIAL PRIMARY KEY,
    request_id     UUID        NOT NULL,
    ts             TIMESTAMPTZ NOT NULL DEFAULT now(),
    method         TEXT,
    path           TEXT,
    query_string   TEXT,
    status_code    INT,
    duration_ms    FLOAT,
    client_ip      TEXT,
    user_agent     TEXT
);

CREATE INDEX ON audit.api_requests (ts DESC);
CREATE INDEX ON audit.api_requests (path);
