# The semantic model, starting from 5,000 unmodelled tables

## The problem this solves

The semantic model is not optional. It is what makes the guards, the cache key
and the agent safe:

- The compiler can only write SQL for metrics it knows the grain of.
- The cache key includes the model fingerprint, so a definition change
  invalidates results computed under the old one.
- The agent's entire vocabulary is this file. Without it, "AI-friendly" means
  an LLM writing SQL against thousands of raw columns, which is a coin flip you
  cannot audit.

But **hand-authoring it does not survive contact with 5,000 tables.** A
platform you cannot use until the modelling is finished is a platform nobody
adopts.

So the model is **generated, then curated incrementally**. A generated model is
a real model: the compiler, the guards and the cache all work against it
unchanged from the moment it lands.

---

## The workflow

```
 1. rank            which of the 5,000 tables are actually queried
 2. introspect      generate draft YAML for the top N
 3. build           write dashboards against the draft — it works today
 4. curate          delete noise, rename, add owners and tests
 5. measure         GET /models/{name}/coverage  →  curation debt as a number
```

Steps 3 and 4 run in parallel and forever. You never "finish" modelling; you
raise the curated share.

---

## 1. Find the tables that matter

Do not model 5,000 tables. Most are not queried by anyone. Snowflake knows
which ones are:

```bash
cd backend
FRAME_ENGINE=snowflake python -m frame.introspect --rank-by-usage --top 25 --usage-days 90
```

Reads `SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY` joined to `QUERY_HISTORY` and
prints tables by real query volume and distinct users.

> Requires a role with `IMPORTED PRIVILEGES` on the `SNOWFLAKE` database.
> `ACCOUNT_USAGE` views lag by up to ~3 hours, which does not matter for a
> 90-day ranking.

You can also just look:

```bash
python -m frame.introspect --list --schema OPS --database ANALYTICS
python -m frame.introspect --list --like "FCT_%"
```

---

## 2. Generate a draft model

```bash
python -m frame.introspect \
  --database ANALYTICS --schema OPS \
  --tables FCT_EXCEPTION,AGG_TEAM_SLA \
  --name ops \
  --out models/ops.yml
```

This runs two cheap queries per table: one against `INFORMATION_SCHEMA.COLUMNS`,
and one profiling query using `APPROX_COUNT_DISTINCT` over a recent window
(`--profile-days`, default 90) so a clustered fact table prunes rather than
scans.

Every generated definition is written with `curated: false`.

### What it infers

| Column | Becomes | Rule |
|---|---|---|
| `DATE` / `TIMESTAMP` | time dimension | Best-named one becomes the source's `time_column` |
| `BOOLEAN` | dimension | |
| `VARCHAR`, ≤ 500 distinct | dimension | In the grain if ≤ 200 distinct |
| `VARCHAR`, > 500 distinct | distinct-count metric | Too many values to group by |
| numeric ending `_id`/`_key`/`_code` | `count_distinct` metric | `approx: true` above 100k distinct |
| numeric matching `rate`/`pct`/`ratio`/`score` | `avg` metric | Summing a ratio is meaningless |
| numeric matching `_days`/`_hours`/`duration`/`age` | `avg` metric, **flagged** | Ambiguous — summing effort is valid, summing age is not |
| other numeric | `sum` metric | Currency format if the name looks like money |
| `VARIANT` / `OBJECT` / `ARRAY` | skipped | Listed in `x-introspection-notes` |
| every table | `<entity>.row_count` | The one measure that is always correct |

Table prefixes (`fct_`, `dim_`, `agg_`, `stg_`, `vw_`, …) are stripped to form
the metric namespace: `FCT_EXCEPTION` → `exception.count`.

### Tuning

| Flag | Default | Effect |
|---|---|---|
| `--max-dimension-cardinality` | 500 | Above this, a text column is a metric not a dimension |
| `--profile-days` | 90 | Profile a recent window; `0` for all history |
| `--no-profile` | off | Skip profiling entirely. Faster, much worse inference |

---

## 3. Build a dashboard immediately

The draft is a working model. Point a spec at it and go — see
[`authoring-specs.md`](./authoring-specs.md).

```bash
curl -s localhost:8000/api/v1/models/ops | python -m json.tool
```

Everything works: guards, grain enforcement, row-level security, caching, the
validator. The only thing `curated: false` changes is that the metric is not
claiming to have been reviewed.

---

## 4. Curate

Curation is editing a YAML file. Do it in this order, because the first step
removes most of the work:

**Delete.** Introspection is deliberately generous. A 40-column table produces
~30 definitions and you probably want six. Deleting is the highest-value edit.

**Rename.** `exception.amount_usd` → `exception.value_usd` if that is what
people say. Add `synonyms` for what they say informally — the agent reads them.

**Fix the flagged ones.** Anything with a `note` about an ambiguous aggregate
needs a human decision. Search for them:

```bash
grep -n "curated: false" models/ops.yml | wc -l
grep -n "Aggregate inferred" models/ops.yml
```

**Then promote.** A curated metric requires an `owner` and at least one entry in
`tests` — the model refuses to load otherwise.

```yaml
  - name: exception.count
    label: Open exceptions
    kind: measure
    source: fct_exception
    agg: count_distinct
    column: exception_id
    filters: ["status IN ('OPEN','PENDING')"]   # add the business rule
    grain: [exception.as_of_date, exception.team, exception.reason_code]
    format: { style: integer }
    direction: lower_is_better                  # decides good/bad colouring
    owner: fin-ops-platform                     # required to curate
    tests: [non_negative, no_gaps_by_day]       # required to curate
    synonyms: [exceptions, "open items", breaks]
    curated: true                               # <- the promotion
```

### Adding definitions introspection cannot infer

**Ratios** are `kind: derived` over other metrics — never a second `agg`:

```yaml
  - name: exception.resolution_rate
    kind: derived
    expr: "{exception.closed_count} / NULLIF({exception.closed_count} + {exception.count}, 0)"
    format: { style: percent, precision: 1 }
    direction: higher_is_better
    owner: fin-ops-platform
    tests: [between_zero_and_one]
```

**Anomaly ranking** needs a `baseline` on the measure, which publishes
`{metric@avg_28d}` and `{metric@stddev_28d}`:

```yaml
  - name: exception.count
    baseline: { window_days: 28, stats: [avg, stddev] }

  - name: severity.signed_z
    kind: derived
    expr: "({exception.count} - {exception.count@avg_28d}) / NULLIF({exception.count@stddev_28d}, 0)"
    note: >
      Signed. A large improvement ranks as high as a large regression, but is
      never styled as a warning. Rank on absolute value; colour on sign.
```

---

## 5. Measure the debt

```bash
curl -s localhost:8000/api/v1/models/ops/coverage | python -m json.tool
```

```jsonc
{
  "metrics":    { "total": 31, "curated": 8, "ratio": 0.2581 },
  "dimensions": { "total": 22, "curated": 5, "ratio": 0.2273 },
  "sources":    { "total": 2, "curated": 0, "withoutTimeColumn": [] },
  "debt": {
    "unowned": [...],            // no owner
    "untested": [...],           // no test
    "flaggedForReview": [...]    // ambiguous aggregate inferred
  }
}
```

Track `metrics.ratio` per model. It is the honest measure of whether the
semantic layer is becoming an asset or a dumping ground.

---

## Promoting a dashboard calculation

Dashboards can define their own calculations (`calc.*`, see
[`authoring-specs.md`](./authoring-specs.md#defining-a-metric-from-the-dashboard)).
They are scoped to one spec and never enter the shared namespace, which is what
makes them safe to create without review.

They are also a demand signal. If five dashboards independently define the same
ratio, that is the argument for promoting it — and unlike a feature request, it
is a fact you can query:

```bash
grep -h '"expr"' backend/specs/*.json | sort | uniq -c | sort -rn | head
```

To promote one, move it into the model and give it what a governed metric needs:

```yaml
  - name: exception.value_per_item        # drop the calc. prefix
    label: Average exposure
    kind: derived
    expr: "{exception.value_usd} / NULLIF({exception.count}, 0)"
    format: { style: currency, currency: USD }
    direction: lower_is_better
    owner: fin-ops-platform               # required
    tests: [non_negative]                 # required
    synonyms: ["exposure per item", "average exposure"]
```

Then delete the `calc.` version from each spec and point the blocks at the new
name. The dashboards keep working; the definition is now reviewed, testable and
reusable.

**Do not promote everything.** A calculation used by one dashboard should stay
in that dashboard. Promotion is for definitions that more than one team relies
on — otherwise the model becomes the dumping ground the `calc.` prefix exists to
prevent.

---

## Governance, which is the real risk

The failure mode is not technical. It is a model with 1,200 metrics and four
spellings of revenue — the original estate, in YAML.

- **Cap it.** Eighty well-defined metrics cover the large majority of a
  thousand dashboards. If a model passes a few hundred curated metrics, that is
  a signal to consolidate, not to celebrate.
- **An owner must be able to say no** to a near-duplicate. If that authority
  does not exist organisationally, no amount of loader validation substitutes
  for it.
- **Drafts are fine; unowned curated metrics are not.** `curated: true` without
  a real owner is worse than `curated: false`, because it claims a review that
  did not happen.

---

## Reference: model fields

### Source

| Field | Notes |
|---|---|
| `relation` | Fully qualified, e.g. `ANALYTICS.OPS.FCT_EXCEPTION`. Used by Snowflake. |
| `local` | DuckDB fixture name. Used only by the local engine. |
| `time_column` | Optional. Without it the source cannot be compared across dates or charted as a series. |
| `row_estimate` | Set by introspection. Drives the `large_unfiltered_scan` guard. |
| `curated` | `false` until reviewed. |

### Dimension

| Field | Notes |
|---|---|
| `name`, `label`, `source`, `column` | Required. |
| `kind` | `categorical` (default) or `time`. |
| `cardinality` | Approximate distinct count from profiling. |
| `synonyms` | Read by the agent. |

### Metric

| Field | Applies to | Notes |
|---|---|---|
| `kind` | both | `measure` hits a table; `derived` is an expression over metrics. |
| `source`, `agg`, `column` | measure | `agg`: `sum`, `avg`, `min`, `max`, `count`, `count_distinct`. |
| `filters` | measure | Raw SQL fragments, model-authored. Compiled to `CASE WHEN`. |
| `approx` | measure | `count_distinct` only. Uses `APPROX_COUNT_DISTINCT`. |
| `baseline` | measure | `{window_days, stats}`. Publishes `{metric@avg_Nd}`. |
| `expr` | derived | References `{metric}` or `{metric@stat}`. |
| `grain` | measure | The dimensions it may be sliced by. |
| `direction` | both | `higher_is_better`, `lower_is_better`, `neutral`. |
| `cost_class` | both | `cheap`, `moderate`, `expensive`. Routes the warehouse. |
| `owner`, `tests` | both | Required when `curated: true`. |
| `synonyms`, `note` | both | Read by the agent, never by SQL. |

> Top-level keys starting with `x-` are stripped before validation, so YAML
> anchors can host a shared grain list. Everything else is strictly forbidden —
> a typo'd key is a silently missing definition.
