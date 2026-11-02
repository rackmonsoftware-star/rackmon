-- Runs automatically the first time the Postgres data directory is initialised
-- (Docker entrypoint `docker-entrypoint-initdb.d`). It only enables the
-- TimescaleDB extension; the hypertable + continuous aggregates are applied
-- once, after the API has created its tables, via 20-hypertable.sql.
CREATE EXTENSION IF NOT EXISTS timescaledb;
