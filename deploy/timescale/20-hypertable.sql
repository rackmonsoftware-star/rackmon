-- One-time performance upgrade for the time-series table.
--
-- RackMon works on plain PostgreSQL out of the box (it buckets metrics in
-- Python), so this script is OPTIONAL. Apply it once, AFTER the API has started
-- for the first time and created its schema:
--
--   docker compose exec -T db \
--     psql -U rackmon -d rackmon < deploy/timescale/20-hypertable.sql
--
-- It converts `metric_points` into a Timescale hypertable, adds rollups as
-- continuous aggregates, and installs a retention policy. Safe to re-run.

-- ---------------------------------------------------------------------------
-- 1. Hypertable
-- ---------------------------------------------------------------------------
-- The ORM creates `metric_points` with a surrogate integer primary key.
-- Timescale requires the partitioning column (`time`) to be part of every
-- unique constraint, so we drop the default PK (no foreign keys reference it)
-- before creating the hypertable and migrating existing rows.
ALTER TABLE metric_points DROP CONSTRAINT IF EXISTS metric_points_pkey;

SELECT create_hypertable(
    'metric_points', 'time',
    chunk_time_interval => INTERVAL '1 day',
    migrate_data        => TRUE,
    if_not_exists       => TRUE
);

-- Primary read pattern: one device+metric over a time range, newest first.
CREATE INDEX IF NOT EXISTS ix_metric_points_dev_metric_time
    ON metric_points (device_id, metric_id, time DESC);

-- ---------------------------------------------------------------------------
-- 2. Continuous aggregates (1m / 5m / 1h rollups)
-- ---------------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS metric_points_1m
    WITH (timescaledb.continuous) AS
SELECT device_id,
       metric_id,
       time_bucket(INTERVAL '1 minute', time) AS bucket,
       avg(value) AS avg_value,
       min(value) AS min_value,
       max(value) AS max_value,
       max(status) AS worst_status
FROM metric_points
GROUP BY device_id, metric_id, bucket
WITH NO DATA;

CREATE MATERIALIZED VIEW IF NOT EXISTS metric_points_5m
    WITH (timescaledb.continuous) AS
SELECT device_id,
       metric_id,
       time_bucket(INTERVAL '5 minutes', time) AS bucket,
       avg(value) AS avg_value,
       min(value) AS min_value,
       max(value) AS max_value,
       max(status) AS worst_status
FROM metric_points
GROUP BY device_id, metric_id, bucket
WITH NO DATA;

CREATE MATERIALIZED VIEW IF NOT EXISTS metric_points_1h
    WITH (timescaledb.continuous) AS
SELECT device_id,
       metric_id,
       time_bucket(INTERVAL '1 hour', time) AS bucket,
       avg(value) AS avg_value,
       min(value) AS min_value,
       max(value) AS max_value,
       max(status) AS worst_status
FROM metric_points
GROUP BY device_id, metric_id, bucket
WITH NO DATA;

-- Keep the aggregates fresh. (start_offset, end_offset, schedule_interval)
SELECT add_continuous_aggregate_policy('metric_points_1m',
    start_offset => INTERVAL '3 hours',  end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute', if_not_exists => TRUE);
SELECT add_continuous_aggregate_policy('metric_points_5m',
    start_offset => INTERVAL '1 day',    end_offset => INTERVAL '5 minutes',
    schedule_interval => INTERVAL '5 minutes', if_not_exists => TRUE);
SELECT add_continuous_aggregate_policy('metric_points_1h',
    start_offset => INTERVAL '7 days',   end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour', if_not_exists => TRUE);

-- ---------------------------------------------------------------------------
-- 3. Retention + compression
-- ---------------------------------------------------------------------------
-- Drop raw points older than 30 days (rollups above are retained longer).
SELECT add_retention_policy('metric_points', INTERVAL '30 days', if_not_exists => TRUE);

-- Compress chunks older than 7 days to save space on historical data.
ALTER TABLE metric_points SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'device_id, metric_id'
);
SELECT add_compression_policy('metric_points', INTERVAL '7 days', if_not_exists => TRUE);
