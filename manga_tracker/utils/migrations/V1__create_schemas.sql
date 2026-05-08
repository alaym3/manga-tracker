-- V1__create_schemas.sql
-- Create top-level schemas for separation of concerns

CREATE SCHEMA IF NOT EXISTS raw;        -- raw API payloads, never modified after insert
CREATE SCHEMA IF NOT EXISTS staging;       -- cleaned, normalized tables
CREATE SCHEMA IF NOT EXISTS core; -- aggregated/denormalized views for Metabase
CREATE SCHEMA IF NOT EXISTS mage;       -- pipeline run metadata and logs