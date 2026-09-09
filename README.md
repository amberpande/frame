# Frame

[![License](https://img.shields.io/badge/license-Apache%202.0-0B6E63.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB.svg?logo=python&logoColor=white)](backend/pyproject.toml)
[![React](https://img.shields.io/badge/react-18-61DAFB.svg?logo=react&logoColor=black)](frontend/package.json)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688.svg?logo=fastapi&logoColor=white)](backend/frame/main.py)
[![Warehouse](https://img.shields.io/badge/warehouse-Snowflake%20%7C%20DuckDB-29B5E8.svg?logo=snowflake&logoColor=white)](docs/snowflake-live.md)

**Dashboards as data.** One React runtime renders any dashboard from a
versioned JSON spec, over a governed semantic layer on Snowflake.

Adding a dashboard is an `INSERT`. Editing one is an `UPDATE`. Nothing builds,
nothing deploys, nothing scales independently — which is the whole point when
the target is 1,000+ dashboards rather than one.

This repo is **Phase 0**: the inversion, proven end to end. Four dashboards,
thirty-six blocks, eight visualizations, one runtime. The plan the phases come
from is in
[the architecture blueprint](https://claude.ai/code/artifact/6870aeea-5998-4203-af80-9b540ba5f9c6).

---

## Licence

Apache License 2.0 — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
Copyright 2026 Amber Pande.

---

## Documentation

| Doc | For |
|---|---|
| [`docs/authoring-specs.md`](docs/authoring-specs.md) | **Creating a dashboard.** The complete procedure. |
| [`docs/semantic-model.md`](docs/semantic-model.md) | Bootstrapping a model from an unmodelled warehouse, and curating it |
| [`docs/snowflake-live.md`](docs/snowflake-live.md) | Live Snowflake connection, cost controls, what to tune |
| [`docs/deployment.md`](docs/deployment.md) | **Running on ECS.** Why Redis is not a sidecar, sizing, what to watch |
| [`AGENTS.md`](AGENTS.md) | Coding agents. Copilot also reads `.github/copilot-instructions.md`. |

## No semantic layer yet? Start here

You do not need to model 5,000 tables before using this. Generate a draft and
curate it incrementally — a generated model is a real model, and every guard,
the cache and the validator work against it unchanged.

```bash
cd backend
FRAME_ENGINE=snowflake python -m frame.introspect --rank-by-usage --top 25
python -m frame.introspect --database ANALYTICS --schema OPS \
  --tables FCT_ORDERS,DIM_CUSTOMER --name ops --out models/ops.yml
curl -s localhost:8000/api/v1/models/ops/coverage    # curation debt, as a number
```

Everything generated is `curated: false`. See
[`docs/semantic-model.md`](docs/semantic-model.md).

## Quickstart

Two terminals. No warehouse credentials needed — the whole stack runs against a
local DuckDB fixture.

```bash
# 1. backend
cd backend
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -e ".[dev]"   # Windows
# source .venv/bin/activate && pip install -e ".[dev]"  # macOS / Linux
python seed/build_seed.py                              # builds data/frame.duckdb
python -m uvicorn frame.main:app --port 8000

# 2. frontend
cd frontend
npm install
npm run dev            # http://localhost:5173
```

```bash
cd backend  && python -m pytest -q      # 22 passed
cd frontend && npm run typecheck
```

> The seed script opens the fixture read-write and the server holds it
> read-only, so **stop the server before re-seeding**.

---

## The four dashboards

Pick them from the **Dashboard** menu. Each exists to exercise something
different, so if you break the framework one of them will tell you.

| Spec | Blocks | What it shows off |
|---|---|---|
| `ap-exception-variance` | 9 | The original: two-date variance, severity ranking, explain panel |
| `ops-control-tower` | 12 | Breadth — 76-day multi-series trend, team×priority matrix, five params, eight metrics in one table |
| `vendor-risk` | 8 | **Cross-filtering.** Click a vendor tier; every block below it re-queries |
| `sla-scorecard` | 7 | **Two sources on one page**, at different grains, with the grain guard live |

Things worth clicking:

- In **vendor-risk**, click the `Tail` bar. Every block below says "filtered to
  Tail" and re-queries; the KPI tiles at the top deliberately do not move,
  because they declare no `source`. Click it again to clear.
- In **ops-control-tower**, click a row in *Biggest movers* and read the
  explain panel — the figures, the governed definitions, the compiled SQL.
- Switch **Viewing as** to *Contractor*: the Exposure tile refuses with
  `metric_forbidden` while the rest of the page still renders.
- Watch the tier badge on each block header, and the footer line counting how
  many blocks were served from cache versus the warehouse.

---

## How to use it

### Add a dashboard

Write a JSON file into `backend/specs/`. That is the entire procedure — no
build, no deploy, no restart. Reload the page and it is in the menu.

```jsonc
{
  "id": "my-dashboard",              // must match the filename
  "specVersion": 1,
  "model": "finance_ops",            // which semantic model it speaks
  "title": "My dashboard",
  "freshness": "daily",              // picks the serving tier
  "params": [
    { "name": "as_of", "type": "date", "default": "@latest_close" },
    { "name": "compare_to", "type": "date", "default": "@as_of - 7d" }
  ],
  "blocks": [
    {
      "id": "movers",
      "viz": "mark.dumbbell",        // an id from the viz registry
      "at": { "x": 0, "y": 0, "w": 8, "h": 7 },   // 12-column grid
      "title": "Biggest movers",
      "query": {
        "metrics": ["exception.count", "severity.signed_z"],
        "by": ["exception.reason_code"],
        "compare": "$compare_to",    // -> two observations per group
        "limit": 12                  // top 12 GROUPS, both observations of each
      },
      "encode": { "y": "exception.reason_code", "x": "exception.count" },
      "sort": { "by": "severity.signed_z", "dir": "desc", "abs": true }
    }
  ]
}
```

Or publish over the API, which validates every block against the semantic model
before it is stored:

```bash
curl -X PUT localhost:8000/api/v1/specs/my-dashboard \
  -H "Content-Type: application/json" -d @my-dashboard.json
```

**Params** resolve server-side: `@latest_close` (the max date in the source),
`@today`, `@as_of - 7d`, or a literal `2026-09-08`. A param of type `dimension`
becomes a filter control and applies to every block.

**Cross-filtering** is one line — give a block a `source` alongside its own
`query`, and the selection in that block becomes a filter on this one:

```jsonc
"source": { "block": "tiers", "on": "select" }
```

**Time series** need an explicit window, because the default query is "as of one
date" and grouping by date would otherwise return exactly that date:

```jsonc
"query": {
  "metrics": ["exception.count"],
  "by": ["exception.as_of_date"],
  "windowDays": 76
}
```

### Add a metric

Edit `backend/models/finance_ops.yml`. Every metric needs an `owner` and at
least one entry in `tests` — the model refuses to load otherwise, which is the
cheapest guard against the layer becoming a dumping ground.

```yaml
  - name: exception.p1_count
    label: P1 exceptions
    kind: measure
    source: fct_exception
    agg: count_distinct
    column: exception_id
    filters: ["status IN ('OPEN','PENDING')", "priority = 'P1'"]
    grain: *exception_grain          # what it may legally be sliced by
    format: { style: integer }
    owner: fin-ops-platform
    tests: [non_negative]
    direction: lower_is_better
    synonyms: [P1, critical, urgent] # the agent reads these
```

Ratios are `kind: derived` over other metrics — never a second `agg`:

```yaml
  - name: exception.resolution_rate
    kind: derived
    expr: "{exception.closed_count} / NULLIF({exception.closed_count} + {exception.count}, 0)"
```

`baseline: { window_days: 28, stats: [avg, stddev] }` on a measure publishes
`{metric@avg_28d}` and `{metric@stddev_28d}` for derived metrics to reference —
that is how `severity.signed_z` is a governed definition rather than renderer
code.

The model is served at `GET /api/v1/models/finance_ops`. That single payload is
the builder's palette and the agent's entire vocabulary; nothing outside it
exists.

### Add a visualization

Two files, no builder changes, no deploy of anything else.

1. A manifest in `frontend/src/viz/manifests.ts` — `channels` become the
   builder's drop targets and the agent's argument schema; `goodFor` / `notFor`
   / `invariant` are how a model picks the right mark and how a reviewer
   catches the wrong one.
2. A component in `frontend/src/viz/marks/`, registered in `registry.ts` with
   `lazy(() => import(...))` so it ships as its own chunk.

Eight are registered: `mark.dumbbell`, `mark.bar`, `mark.line`, `mark.matrix`,
`big.number`, `briefing.band`, `table.grid`, `panel.explain`.

A spec naming a `viz` this runtime does not have renders a labelled placeholder
rather than crashing — a runtime must survive meeting a spec written against a
newer catalogue.

---

## Going live on Snowflake

The compiler already emits Snowflake SQL; only the engine and credentials
change.

```bash
# 1. create the objects (database, schema, tables, warehouses, RLS policy)
snowsql -f backend/snowflake/ddl.sql        # or paste into a worksheet

# 2. configure
cp backend/.env.example backend/.env        # then export the vars

# 3. verify the connection before loading anything
cd backend && python seed/push_to_snowflake.py --check

# 4. load the fixture (DuckDB -> Parquet -> stage -> COPY INTO)
python seed/push_to_snowflake.py

# 5. point the query service at the warehouse
FRAME_ENGINE=snowflake python -m uvicorn frame.main:app --port 8000
```

Nothing else changes. The specs, the semantic model, the runtime and the cache
are all identical — `relation:` in the model already names
`ANALYTICS.OPS.FCT_EXCEPTION`, and `local:` is only used by the DuckDB engine.

**What `ddl.sql` sets up beyond the tables**

- **Two warehouses.** `FRAME_INTERACTIVE_XS` is XSMALL and multi-cluster
  (1→3): interactive concurrency scales *out*, not up. `FRAME_BATCH_S` does
  materialisation. Sharing one warehouse means a nightly rebuild can queue
  ahead of a dashboard someone is looking at.
- **A row access policy** on `region`. Push enforcement into the warehouse so
  the guarantee holds even for a query path nobody has thought of yet; the
  compiler still injects the same predicates and still fingerprints them into
  the cache key, because the cache lives outside Snowflake and cannot see a
  policy.
- **A dynamic table**, `CUBE_EXCEPTION_DAILY`, at the grain the Phase 1 cube
  materialiser will write to Parquet.

**The identifier trap.** Snowflake folds unquoted identifiers to upper case at
creation, so a column created as `exception_id` is stored as `EXCEPTION_ID` and
the lower-case `"exception_id"` never resolves. The Snowflake dialect upper-cases
physical columns while leaving output aliases verbatim — the client keys on
`"exception.count"`, which must survive exactly. If you create the tables with
quoted lower-case names instead, quote the column names in the YAML too.
Covered by `test_snowflake_uppercases_physical_columns_but_not_aliases`.

**Untested against a live account.** The Snowflake path is written and
unit-tested at the SQL level, but this repo has never held credentials. Expect
to shake out auth and the first `COPY INTO`; the compiled SQL itself is the part
most likely to be already correct.

**Cost.** Every statement carries `QUERY_TAG = frame:<model>:<planHash>`, so
credits are attributable per dashboard and per plan. Start there when asking
which dashboard is expensive.

---

## The decisions worth knowing

**The compiler is the only component that writes SQL.** Not the builder, not
the agent, and no spec may carry a SQL string. Every guarantee the platform
makes — bounded cost, enforced row-level security, cache correctness,
reproducibility — depends on there being no second path to the warehouse.

**The policy fingerprint is part of every cache key.** Caching keyed on the
query plus row-level security applied per user is the bug that serves one user's
rows to another. `QueryPlan.hash` folds in the compiled SQL, the bound params,
the model fingerprint *and* a hash of the caller's policy. Identical access
shares cache entries; different access cannot collide.

**Slicing a metric outside its grain is a rejection, not a number.**
`sla.breach_rate` comes from a daily summary grained to team only, so cutting it
by reason code fails with a structured `grain_violation`.

**Rejections are machine-readable**, because that is the agent planner's
feedback channel in Phase 3:

```json
{"reason": "grain_violation",
 "detail": "metric 'sla.breach_rate' is not grained on 'exception.reason_code'",
 "allowed": ["sla.as_of_date", "sla.team"]}
```

Others the compiler will refuse: `compare_with_time_series`,
`baseline_with_time_series`, `multi_source_query`, `metric_forbidden`,
`limit_exceeds_cap`, `unbounded_expensive_query`.

**`limit` ranks groups, not rows.** With a comparison, limiting rows would
truncate one side of the pairing and silently misstate every variance on the
page.

**Severity is a governed metric, not renderer code**, so every dashboard ranks
the same way and the agent has a stable name to reference.

**Read-only, one cursor per statement.** A shared DuckDB connection across
FastAPI's threadpool lets concurrent blocks read each other's result sets —
silently, with plausible-looking numbers. Snowflake connections are thread-local
and reused, because a fresh session per query would spend the whole latency
budget on handshakes.

---

## Try the things that matter

```bash
# Row-level security changes the plan hash, not just the rows
for id in analyst emea restricted; do
  curl -s -X POST localhost:8000/api/v1/specs/ops-control-tower/blocks/movers/data \
    -H "Content-Type: application/json" -H "X-Frame-Identity: $id" -d '{"params":{}}' \
  | python -c "import json,sys;m=json.load(sys.stdin)['meta'];print(m['policyFingerprint'],m['planHash'])"
done

# The agent's validator: compile and check without reading a row
curl -s -X POST localhost:8000/api/v1/validate -H "Content-Type: application/json" \
  -d '{"model":"finance_ops","query":{"metrics":["sla.breach_rate"],"by":["exception.reason_code"]}}'

# Cross-filtering, as the runtime sends it
curl -s -X POST localhost:8000/api/v1/specs/vendor-risk/blocks/reasons/data \
  -H "Content-Type: application/json" \
  -d '{"params":{},"filters":[{"field":"exception.vendor_tier","op":"eq","value":"Tail"}]}'
```

---

## The fixture tells a story

A fixture of uniform noise makes every ranking look correct, so the local data
has deliberate events between 25 Jun and 8 Sep 2026:

- **1 Sep** — a vendor master migration spikes `VENDOR_BANK` and breaks
  `INVOICE_MATCH`, which stays broken.
- **3 Sep** — the break cascades into `PAYMENT_RECON`, two days downstream.
- **3 Sep** — an unrelated access recertification window opens, lifting
  `ACCESS_RECERT` sixfold. A separate cause, not part of the migration.
- **2 Sep** — `KYC_REFRESH` improves in a step, so signed severity sees it.
- **Throughout** — `Tail` vendors generate disproportionately many matching
  exceptions, which is what `vendor-risk` exists to surface.

Two causes and one improvement, because a human scanning a grid would blame
everything on a single incident. The ranking puts `PAYMENT_RECON` (+55) above
`INVOICE_MATCH` (+128) — deviation from normal, not raw magnitude.

---

## Not built yet, on purpose

- **Cube materialization and DuckDB-WASM in the browser** (Phase 1). The seam is
  marked in `serve/tiers.py`; nothing above it changes when it lands.
- **Arrow over the wire.** The envelope is already column-oriented so the client
  does not change when it does.
- **The drag-and-drop builder** (Phase 2). The manifests it needs already exist
  and already drive the runtime.
- **The agent planner** (Phase 3). The validator, the grounding payload and the
  structured rejections are in place; the explain panel renders exactly what the
  planner will receive.
- **Spec composition** — templates and shared partials, so forty regional
  dashboards derive from one parent spec rather than forty near-identical rows.
- **Join paths.** A query spanning two sources is refused
  (`multi_source_query`) rather than silently cross-joined; put one block per
  source, as `sla-scorecard` does.
