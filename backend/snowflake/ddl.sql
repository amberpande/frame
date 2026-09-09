-- Frame — Snowflake objects.
--
-- Run once as a role that can create schemas and warehouses, then load data
-- with `python seed/push_to_snowflake.py`.
--
--   snowsql -f snowflake/ddl.sql
--   -- or paste into a worksheet
--
-- Identifiers are deliberately left unquoted, so Snowflake folds them to upper
-- case. The compiler's Snowflake dialect emits upper-case quoted columns to
-- match. If you create these tables with quoted lower-case names instead, quote
-- the column names in models/finance_ops.yml too, or nothing will resolve.

CREATE DATABASE IF NOT EXISTS ANALYTICS;
CREATE SCHEMA IF NOT EXISTS ANALYTICS.OPS;

-- Interactive queries get their own small, auto-suspending, multi-cluster
-- warehouse. Serving and batch must not share one: a nightly rebuild should
-- never be able to queue behind it a dashboard someone is looking at.
CREATE WAREHOUSE IF NOT EXISTS FRAME_INTERACTIVE_XS
  WITH WAREHOUSE_SIZE = 'XSMALL'
       AUTO_SUSPEND = 60
       AUTO_RESUME = TRUE
       MIN_CLUSTER_COUNT = 1
       MAX_CLUSTER_COUNT = 3
       SCALING_POLICY = 'STANDARD'
       COMMENT = 'Frame interactive block queries. Concurrency scales out, not up.';

-- Materialisation and loads. Sized up, but single-cluster: it does one job at
-- a time and nobody is watching a spinner while it runs.
CREATE WAREHOUSE IF NOT EXISTS FRAME_BATCH_S
  WITH WAREHOUSE_SIZE = 'SMALL'
       AUTO_SUSPEND = 60
       AUTO_RESUME = TRUE
       COMMENT = 'Frame cube materialisation and fixture loads.';

USE SCHEMA ANALYTICS.OPS;

CREATE TABLE IF NOT EXISTS FCT_EXCEPTION (
    exception_id  VARCHAR(32)   NOT NULL,
    as_of_date    DATE          NOT NULL,
    team          VARCHAR(64),
    reason_code   VARCHAR(64),
    region        VARCHAR(16),
    process       VARCHAR(16),
    entity        VARCHAR(64),
    vendor_tier   VARCHAR(32),
    priority      VARCHAR(8),
    status        VARCHAR(16),
    age_days      NUMBER(9,0),
    amount_usd    NUMBER(18,2)
)
CLUSTER BY (as_of_date)
COMMENT = 'One row per exception per as-of date. Grain declared in models/finance_ops.yml.';

CREATE TABLE IF NOT EXISTS AGG_TEAM_SLA (
    as_of_date     DATE NOT NULL,
    team           VARCHAR(64),
    breached_count NUMBER(9,0),
    total_count    NUMBER(9,0)
)
CLUSTER BY (as_of_date)
COMMENT = 'Daily summary grained to team only. Metrics here cannot be sliced by reason code or region.';

-- ---------------------------------------------------------------------------
-- Row-level security.
--
-- Push enforcement down to the warehouse so the guarantee holds even for a
-- query path nobody has thought of yet. The compiler still injects the same
-- predicates and still fingerprints them into the cache key — belt and braces,
-- because the cache lives outside Snowflake and cannot see a policy.
-- ---------------------------------------------------------------------------

CREATE ROW ACCESS POLICY IF NOT EXISTS ANALYTICS.OPS.REGION_POLICY
  AS (region VARCHAR) RETURNS BOOLEAN ->
     CURRENT_ROLE() IN ('FRAME_ADMIN', 'FRAME_ANALYST_ALL')
     OR (CURRENT_ROLE() = 'FRAME_ANALYST_EMEA' AND region = 'EMEA')
     OR (CURRENT_ROLE() = 'FRAME_ANALYST_AMER' AND region = 'AMER');

-- Attach it when the roles above exist:
-- ALTER TABLE ANALYTICS.OPS.FCT_EXCEPTION
--   ADD ROW ACCESS POLICY ANALYTICS.OPS.REGION_POLICY ON (region);

-- ---------------------------------------------------------------------------
-- Phase 1: pre-aggregation.
--
-- A dynamic table is the least-effort way to keep a cube fresh without
-- scheduling anything. This is the shape the cube materialiser writes to
-- Parquet later; keeping it here makes the target grain explicit now.
-- ---------------------------------------------------------------------------

CREATE DYNAMIC TABLE IF NOT EXISTS ANALYTICS.OPS.CUBE_EXCEPTION_DAILY
  TARGET_LAG = '1 hour'
  WAREHOUSE = FRAME_BATCH_S
AS
SELECT
    as_of_date,
    team,
    reason_code,
    region,
    process,
    entity,
    vendor_tier,
    priority,
    COUNT(DISTINCT CASE WHEN status IN ('OPEN','PENDING') THEN exception_id END) AS open_count,
    COUNT(DISTINCT CASE WHEN status = 'CLOSED' THEN exception_id END)            AS closed_count,
    COUNT(DISTINCT CASE WHEN status IN ('OPEN','PENDING') AND age_days > 30
                        THEN exception_id END)                                    AS aged_over_30,
    SUM(CASE WHEN status IN ('OPEN','PENDING') THEN amount_usd ELSE 0 END)        AS value_usd,
    AVG(CASE WHEN status IN ('OPEN','PENDING') THEN age_days END)                 AS aging_days
FROM ANALYTICS.OPS.FCT_EXCEPTION
GROUP BY ALL;
