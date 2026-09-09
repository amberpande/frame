# Running live against Snowflake

No semantic views required. Point Frame at your tables, introspect a draft
model, and serve.

---

## Connect

```bash
# 1. warehouses, and optionally the RLS policy
snowsql -f backend/snowflake/ddl.sql      # edit first: you may already have the tables

# 2. credentials
cp backend/.env.example backend/.env      # fill in, then export

# 3. verify before anything else
cd backend && python seed/push_to_snowflake.py --check
```

`--check` prints the resolved account, user, role, warehouse, database and
schema. If that is wrong, nothing downstream will work.

```bash
# 4. serve
FRAME_ENGINE=snowflake python -m uvicorn frame.main:app --port 8000
```

`FRAME_ENGINE` is the only switch. Specs, model, runtime and cache are
identical — the model's `relation:` already names the Snowflake table.

### Authentication

Key-pair is the right choice for a service. SSO (`externalbrowser`) will not
work in a container.

```bash
SNOWFLAKE_ACCOUNT=myorg-myaccount
SNOWFLAKE_USER=frame_service
SNOWFLAKE_PRIVATE_KEY_PATH=/run/secrets/frame_rsa_key.p8
SNOWFLAKE_PRIVATE_KEY_PASSPHRASE=...        # if encrypted
SNOWFLAKE_ROLE=FRAME_ANALYST_ALL
SNOWFLAKE_DATABASE=ANALYTICS
SNOWFLAKE_SCHEMA=OPS
```

### The identifier trap

Snowflake folds unquoted identifiers to **upper case** at creation. A column
created as `exception_id` is stored as `EXCEPTION_ID`, so the lower-case
`"exception_id"` never resolves. This is the most common way a query that works
locally dies on Snowflake.

Frame handles it: the Snowflake dialect upper-cases physical columns and leaves
output aliases verbatim. **If your tables were created with quoted lower-case
names**, quote the column names in the model YAML instead:

```yaml
    column: '"exception_id"'    # passed through untouched
```

---

## What the platform already does for cost

These are in the code, not advice:

| Mechanism | Where | Effect |
|---|---|---|
| **Result cache** keyed on the compiled plan | `serve/tiers.py` | Most block loads never reach Snowflake at all |
| **Always filters the time column** | `compile/compiler.py` | Partition pruning on a clustered fact table |
| **Projects only needed columns** | compiler | Never `SELECT *` |
| **Pushes `LIMIT`** | compiler | Ranked CTE caps rows at the warehouse |
| **`QUERY_TAG = frame:<model>:<planHash>`** | `serve/engine.py` | Cost attributable per dashboard and per plan |
| **`STATEMENT_TIMEOUT_IN_SECONDS`** | engine, per session | A runaway query dies instead of holding a warehouse |
| **Connections reused per worker thread** | engine | A session handshake is a few hundred ms; a 12-block dashboard would spend its whole budget on them |
| **`APPROX_COUNT_DISTINCT`** where the model opts in | compiler | HyperLogLog instead of exact distinct on high-cardinality columns |
| **Warehouse routing by cost class** | engine | Heavy blocks off the interactive cluster |
| **Refuses unbounded scans of very large sources** | `compile/guard.py` | `large_unfiltered_scan` |

### Warehouse configuration

Two warehouses, always:

```sql
CREATE WAREHOUSE FRAME_INTERACTIVE_XS
  WITH WAREHOUSE_SIZE = 'XSMALL' AUTO_SUSPEND = 60 AUTO_RESUME = TRUE
       MIN_CLUSTER_COUNT = 1 MAX_CLUSTER_COUNT = 3 SCALING_POLICY = 'STANDARD';

CREATE WAREHOUSE FRAME_BATCH_S
  WITH WAREHOUSE_SIZE = 'SMALL' AUTO_SUSPEND = 60 AUTO_RESUME = TRUE;
```

Interactive concurrency scales **out** (more clusters), not up (bigger
warehouse). A bigger warehouse makes one query faster; more clusters let fifty
people load a dashboard at once. Sharing one warehouse between serving and
batch means a nightly rebuild can queue ahead of a dashboard someone is looking
at.

Route heavy blocks away from the interactive cluster:

```bash
FRAME_SNOWFLAKE_WAREHOUSE_HEAVY=FRAME_BATCH_S
```

Any plan whose `cost_class` is `moderate` or `expensive` runs there instead.
Set `cost_class` on the metric in the model.

### Cost guards

```bash
FRAME_MAX_ROWS=50000              # the compiler will not emit past this
FRAME_STATEMENT_TIMEOUT=30        # seconds
FRAME_LARGE_TABLE_ROWS=50000000   # unfiltered scans above this are refused
```

`large_unfiltered_scan` fires when a source has **no time column**, a
`row_estimate` above the threshold, and the query has no filters. Introspection
fills `row_estimate` — so run it, or the guard cannot help you.

---

## Things to do in Snowflake itself

Frame cannot do these for you, and they matter more than anything above.

**Cluster your fact tables on the date column.** Every Frame query filters it,
so clustering turns a full scan into a few partitions. This is the single
largest lever.

```sql
ALTER TABLE ANALYTICS.OPS.FCT_EXCEPTION CLUSTER BY (as_of_date);
```

**Create dynamic tables for hot aggregates.** If a dashboard is slow and
popular, pre-aggregate it at the grain it queries, then point the model's
`relation` at the dynamic table instead of the fact.

```sql
CREATE DYNAMIC TABLE ANALYTICS.OPS.CUBE_EXCEPTION_DAILY
  TARGET_LAG = '1 hour' WAREHOUSE = FRAME_BATCH_S
AS SELECT as_of_date, team, reason_code, region,
          COUNT(DISTINCT CASE WHEN status IN ('OPEN','PENDING') THEN exception_id END) AS open_count
   FROM ANALYTICS.OPS.FCT_EXCEPTION GROUP BY ALL;
```

Add it to the model as a second source with its own, narrower `grain`. The
grain guard then stops anyone slicing it in a way it cannot support.

**Push row-level security into Snowflake.** Frame injects predicates and
fingerprints them into the cache key, but the cache lives outside Snowflake and
cannot see a policy. A row access policy holds even for a query path nobody has
thought of.

**Set resource monitors.** Frame refuses unbounded queries; it cannot refuse a
badly-clustered table being scanned a thousand times.

---

## Verifying, and what to watch

Every block header shows which tier answered it and how long it took. The
footer counts cache versus warehouse. That mix is the number to manage.

Attribute cost per dashboard using the query tag:

```sql
SELECT
    SPLIT_PART(query_tag, ':', 2)  AS model,
    SPLIT_PART(query_tag, ':', 3)  AS plan_hash,
    COUNT(*)                       AS executions,
    SUM(total_elapsed_time)/1000   AS total_seconds,
    AVG(bytes_scanned)/POWER(1024,3) AS avg_gb_scanned
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE query_tag LIKE 'frame:%'
  AND start_time >= DATEADD(day, -7, CURRENT_TIMESTAMP())
GROUP BY 1, 2
ORDER BY total_seconds DESC
LIMIT 20;
```

Then find which spec that plan hash belongs to by re-running the block with
`{"explain": true}`.

---

## Known limits

- **Untested against a live account.** The Snowflake path is written and
  unit-tested at the SQL level, but this repository has never held credentials.
  Expect to shake out auth and the first load. The compiled SQL is the part
  most likely to be already correct.
- **No cross-source joins.** A query spanning two sources is refused. One block
  per source.
- **No cube tiers yet.** Every cache miss reaches Snowflake. The browser-local
  tier that makes interaction independent of concurrency is Phase 1.
- **The result cache is per process.** Move it to Redis before running several
  tasks, or the hit rate falls as you scale out.
