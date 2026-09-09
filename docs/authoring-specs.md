# How to create a dashboard spec

A dashboard is a JSON file in `backend/specs/`. Creating one requires no build,
no deploy and no restart. Write the file, reload the page.

There are two ways to write one.

**In the browser.** Open the dashboard and press **Edit**. Drag blocks by the
grip bar, resize from the corner, and use the inspector to change the title,
the visualization, the query and every chart option. **Save** publishes it back
to the same JSON row; **Copy JSON** puts the document on your clipboard. Nothing
in the inspector is chart-specific — the controls are generated from the
visualization's manifest, so a new mark appears there with no builder change.

**By hand or by agent**, which is what the rest of this document describes.
The two are interchangeable: the builder edits the same file, and a save writes
a minimal document with defaults omitted, so hand-edits and builder edits do not
fight each other.

This document is the complete procedure. Follow it in order.

---

## Rules

These are absolute. A spec that breaks one is rejected.

1. **A spec never contains SQL.** There is no field for it. Queries are
   expressed as metric and dimension names; the compiler writes the SQL.
2. **Only use metrics and dimensions that exist in the model.** Fetch the list
   first (step 1). Inventing a name produces `unknown_metric`.
3. **`limit` selects top-N groups, not rows.** Both observations of each group
   are returned when `compare` is set.
4. **A time dimension in `by` requires `windowDays`**, and forbids `compare`.
5. **The filename must equal the `id`.** `specs/vendor-risk.json` has
   `"id": "vendor-risk"`.
6. **Validate before publishing** (step 5). It costs nothing and reads no data.

---

## Step 1 — Read the semantic model

Never guess a metric name.

```bash
curl -s localhost:8000/api/v1/models/finance_ops | python -m json.tool
```

Returns every `metrics[].name`, its `grain` (the dimensions it may be sliced
by), its `format`, its `direction`, and `synonyms`. Also returns every
`dimensions[].name`.

The two fields that decide whether a query is legal:

| Field | Meaning |
|---|---|
| `metrics[].grain` | The **only** dimensions this metric may appear in `by` with. |
| `dimensions[].kind` | `time` dimensions trigger series mode. Everything else is `categorical`. |

If the metric you need does not exist, see
[`semantic-model.md`](./semantic-model.md) — add it there, not in the spec.

---

## Step 2 — Start the file

```json
{
  "$schema": "../schemas/spec.schema.json",
  "id": "my-dashboard",
  "specVersion": 1,
  "model": "finance_ops",
  "title": "My dashboard",
  "description": "One sentence on what question this answers.",
  "freshness": "daily",
  "owner": "your-team",
  "tags": ["finance"],
  "params": [],
  "blocks": []
}
```

`$schema` gives editors and coding agents completion and inline validation.
Always include it.

### `freshness` — pick one

| Value | Cache TTL | Use when |
|---|---|---|
| `daily` | 12 h | Data refreshes once a day. **Default choice.** |
| `hourly` | 55 min | Data refreshes intraday. |
| `near_real_time` | 60 s | Operational monitoring. |
| `live` | none | Only with a written `justification`. Bills one warehouse query **per viewer**. |

---

## Step 3 — Declare params

Params render as controls and apply to every block.

```json
"params": [
  { "name": "as_of",      "type": "date", "label": "As of",       "default": "@latest_close" },
  { "name": "compare_to", "type": "date", "label": "Compared to", "default": "@as_of - 7d" },
  { "name": "region",     "type": "dimension", "label": "Region",
    "of": "exception.region", "multi": true }
]
```

**Declare a date param named `as_of` if any block has a query.** It becomes the
as-of date for the whole page.

Date defaults resolve server-side:

| Token | Resolves to |
|---|---|
| `@latest_close`, `@latest`, `@max_date` | `MAX(time_column)` in the source |
| `@today` | Today |
| `@as_of - 7d` | Relative to an **earlier-declared** param. Units `d`, `w`, `m` |
| `2026-09-08` | A literal date |

A `dimension` param needs `of` set to a real dimension name. `multi: true`
produces an `IN` filter.

---

## Step 4 — Add blocks

Every block needs `id`, `viz`, and `at`. Blocks are placed on a **12-column
grid**; one row is 62 px tall.

```json
{
  "id": "movers",
  "viz": "mark.dumbbell",
  "at": { "x": 0, "y": 5, "w": 8, "h": 7 },
  "title": "Biggest movers by reason code",
  "subtitle": "Ranked by deviation from the 28-day normal",
  "query": {
    "metrics": ["exception.count", "severity.signed_z"],
    "by": ["exception.reason_code"],
    "compare": "$compare_to",
    "limit": 12
  },
  "encode": { "y": "exception.reason_code", "x": "exception.count" },
  "sort": { "by": "severity.signed_z", "dir": "desc", "abs": true }
}
```

`x + w` must be ≤ 12. Blocks must not overlap — check `y` and `h` against
neighbours yourself; the schema does not detect overlap.

### Choose the visualization

| `viz` | Use for | Requires | Never use for |
|---|---|---|---|
| `big.number` | One headline figure | 1 metric, no `by` (or `limit: 1`) | Anything with several categories |
| `briefing.band` | Written summary at the top of a page | `by` 1 dim, `compare` | Precise comparison |
| `mark.dumbbell` | **Two dates** compared by category | `by` 1 dim, `compare` | 3+ periods; no comparison |
| `mark.bar` | Ranked magnitude | `by` 1 dim | Emphasising change over time |
| `mark.line` | **Many dates** — a real series | `by` a **time** dim, `windowDays` | Exactly two dates |
| `mark.matrix` | Two-way breakdown | `by` **2** dims | Precise reading; one dim |
| `table.grid` | Exact values, several metrics | `by` 1 dim | Showing shape or trend |
| `panel.explain` | "Why did this move" | `source`, no `query` | Free-form chat |

**The most common mistake:** using `mark.line` for a two-date comparison. Two
observations are not a trend — a line asserts a path nobody measured. Use
`mark.dumbbell`.

### Write the query

```jsonc
"query": {
  "metrics": ["exception.count"],        // required, from the model
  "by": ["exception.team"],              // must be within every metric's grain
  "compare": "$compare_to",              // two periods; omit for a single date
  "windowDays": 90,                      // ONLY when `by` has a time dimension
  "limit": 12,                           // top-N groups
  "filters": [
    { "field": "exception.region", "op": "in", "value": ["EMEA", "AMER"] }
  ],
  "order": { "by": "severity.signed_z", "dir": "desc", "abs": true }
}
```

Filter operators: `eq`, `ne`, `in`, `not_in`, `gt`, `gte`, `lt`, `lte`,
`contains`. `field` must be a **dimension** — filtering a metric is rejected.

Use `"abs": true` when sorting by a signed metric such as `severity.signed_z`,
so a large improvement ranks alongside a large regression.

### Encode channels

`encode` maps a channel to a field name. Read the table above for what each
mark expects.

```json
"encode": { "y": "exception.team", "x": "exception.count" }
"encode": { "x": "exception.as_of_date", "y": "exception.count", "series": "exception.team" }
"encode": { "y": "exception.team", "x": "exception.priority", "value": "exception.count" }
```

If `encode` is omitted, the mark uses the first dimension and first metric.

### Cross-filter one block from another

Add `source` **alongside** the block's own `query`. Clicking in the source
block filters this one.

```json
"source": { "block": "tiers", "on": "select" }
```

The source block must exist, and a block cannot source from itself.

### Add an explain panel

A block with `source` and **no** `query` renders from the source block's data.

```json
{
  "id": "why",
  "viz": "panel.explain",
  "at": { "x": 8, "y": 5, "w": 4, "h": 7 },
  "title": "Why did this move?",
  "source": { "block": "movers", "on": "select" },
  "agent": {
    "task": "variance-explain",
    "grounding": ["query.sql", "query.result", "model.definitions", "block.selection"]
  }
}
```

---

## Step 5 — Validate, then publish

Validate each block's query without reading any data:

```bash
curl -s -X POST localhost:8000/api/v1/validate \
  -H "Content-Type: application/json" \
  -d '{"model":"finance_ops",
       "query":{"metrics":["exception.count"],"by":["exception.team"]}}'
```

`{"ok": true, ...}` means it compiles. `{"ok": false, "error": {...}}` returns a
`reason` code — fix it and retry. See the reason table below.

Then publish. Writing the file into `backend/specs/` is enough; the API route
additionally validates every block against the model:

```bash
curl -s -X PUT localhost:8000/api/v1/specs/my-dashboard \
  -H "Content-Type: application/json" -d @my-dashboard.json
```

Confirm it renders:

```bash
curl -s -X POST localhost:8000/api/v1/specs/my-dashboard/blocks/movers/data \
  -H "Content-Type: application/json" -d '{"params":{}}' | python -m json.tool
```

---

## Refusal codes and what to do

| `reason` | Fix |
|---|---|
| `unknown_metric` | Use a name from `GET /models/{name}`. The error lists `available`. |
| `unknown_dimension` | Same, for dimensions. |
| `grain_violation` | The metric cannot be sliced that way. The error lists `allowed`. |
| `metric_forbidden` | The viewing identity may not read that metric. |
| `metric_filter_unsupported` | `filters[].field` must be a dimension, not a metric. |
| `unknown_sort_field` | Sort by a selected dimension or a known metric. |
| `limit_exceeds_cap` | Lower `limit` below `FRAME_MAX_ROWS`. |
| `multi_source_query` | Metrics come from two tables. Split into one block per source. |
| `compare_with_time_series` | Remove `compare`, or remove the time dimension from `by`. |
| `baseline_with_time_series` | Chart the base metric instead of the severity metric. |
| `no_time_column` | The source has no date column, so it cannot compare or chart a series. |
| `multiple_time_dimensions` | Only one time dimension in `by`. |
| `large_unfiltered_scan` | Add a `filters` entry, or model a time column on the source. |
| `unbounded_expensive_query` | Add `by` or `limit`. |

---

## A complete minimal example

```json
{
  "$schema": "../schemas/spec.schema.json",
  "id": "team-exceptions",
  "specVersion": 1,
  "model": "finance_ops",
  "title": "Team exceptions",
  "description": "Open exceptions by team, week on week.",
  "freshness": "daily",
  "owner": "fin-ops-platform",
  "params": [
    { "name": "as_of", "type": "date", "label": "As of", "default": "@latest_close" },
    { "name": "compare_to", "type": "date", "label": "Compared to", "default": "@as_of - 7d" }
  ],
  "blocks": [
    {
      "id": "total",
      "viz": "big.number",
      "at": { "x": 0, "y": 0, "w": 4, "h": 2 },
      "title": "Open exceptions",
      "query": { "metrics": ["exception.count"], "compare": "$compare_to" }
    },
    {
      "id": "by-team",
      "viz": "mark.bar",
      "at": { "x": 0, "y": 2, "w": 12, "h": 6 },
      "title": "By team",
      "query": {
        "metrics": ["exception.count"],
        "by": ["exception.team"],
        "compare": "$compare_to"
      },
      "encode": { "y": "exception.team", "x": "exception.count" },
      "sort": { "by": "exception.count", "dir": "desc" }
    }
  ]
}
```

---

## Checklist before you finish

- [ ] `$schema` is present and `id` matches the filename
- [ ] Every metric and dimension name came from `GET /models/{name}`
- [ ] Every `by` dimension is inside every requested metric's `grain`
- [ ] `x + w ≤ 12` on every block, and no two blocks overlap
- [ ] Blocks using `compare` reference a declared param
- [ ] Any `mark.line` block has `windowDays` and no `compare`
- [ ] Any `source` names an existing block
- [ ] `freshness` is not `live` without a `justification`
- [ ] `POST /api/v1/validate` returns `ok: true` for every block's query


---

## Customising a chart

Every visualization declares its own options in
`frontend/src/viz/manifests.ts`. They are typed and defaulted, so:

- the inspector renders a control for each one automatically,
- an agent can set them without guessing,
- a spec stores only what differs from the default.

```jsonc
{
  "id": "movers",
  "viz": "mark.dumbbell",
  "options": {
    "showSeverity": false,        // only the changes are stored
    "connectorWeight": "heavy"
  }
}
```

An option that is not declared for that mark is ignored rather than trusted —
specs are editable data and may be older than the mark.

| Mark | Options |
|---|---|
| `mark.dumbbell` | `showSeverity`, `showPercent`, `labelWidth`, `connectorWeight` |
| `mark.bar` | `showGhost`, `showValue`, `showDelta`, `labelWidth` |
| `mark.line` | `showArea`, `showEndpoint`, `strokeWidth`, `yFromZero`, `tickCount` |
| `mark.matrix` | `showValues`, `intensity`, `scale` |
| `big.number` | `size`, `showDelta`, `showPercent`, `goodDirection` |
| `briefing.band` | `threshold`, `showChips`, `maxChips` |
| `table.grid` | `density`, `zebra`, `showRank` |
| `panel.explain` | `showSql`, `showDefinitions` |

To add an option to a mark, add an `OptionSpec` to its manifest and read it in
the component with `bool()`, `num()` or `str()` from `viz/options.ts`. The
inspector needs no change.


---

## Defining a metric from the dashboard

There are two kinds of new metric, and they are not interchangeable.

| You need | It is a | Where it lives | Who can add it |
|---|---|---|---|
| A combination of metrics that already exist — a ratio, a share, a rate | **calculation** | The spec | Anyone editing the dashboard |
| A new aggregate over a raw column — a `SUM`, a `COUNT DISTINCT`, a filtered count | **measure** | The semantic model | Requires an owner and a test |

The split is not bureaucracy. A calculation references only governed metric
names, so it cannot introduce a column, a table or a join, and its grain is
inherited from its inputs. A measure introduces all of those, which is exactly
why it needs a grain, an owner and a test.

### Adding a calculation

In the builder: **Edit → Calculated metrics → New calculation**. The formula is
validated on the server as you type, by the same code that runs at publish time,
so the editor cannot accept something the platform will later reject.

In a spec, it is a top-level `metrics` array:

```json
"metrics": [
  {
    "name": "calc.exposure_per_item",
    "label": "Exposure per item",
    "expr": "{exception.value_usd} / NULLIF({exception.count}, 0)",
    "format": { "style": "currency", "currency": "USD" },
    "direction": "lower_is_better"
  }
]
```

Then use `calc.exposure_per_item` in any block's `query.metrics`, exactly like a
model metric.

**Rules**

- The name must start with `calc.` — so reading any dashboard tells you at a
  glance which of its metrics are governed and which are not.
- `{metric.name}` references only. A bare `amount_usd` is refused: it would be a
  column reference escaping the semantic layer.
- Arithmetic `+ - * / ( )` and these scalar functions: `NULLIF`, `COALESCE`,
  `ABS`, `ROUND`, `FLOOR`, `CEIL`, `GREATEST`, `LEAST`, `POWER`, `SQRT`, `LN`,
  `LOG`, `EXP`, `SIGN`, `MOD`.
- No aggregates. The operands are already aggregated, so `SUM(...)` here would
  be a second, meaningless aggregation.
- All inputs must come from one source table. Mixing sources is refused with
  `multi_source_calculation` while you type, because the compiler cannot join
  across sources.
- A calculation may build on an earlier calculation in the same spec, never a
  later one.
- It may not shadow a metric in the model.

Check one without opening the builder:

```bash
curl -s -X POST localhost:8000/api/v1/expressions/validate   -H "Content-Type: application/json"   -d '{"model":"finance_ops","expr":"{exception.p1_count} / NULLIF({exception.count},0)"}'
```

Returns `{"ok": true, "references": [...], "grain": [...]}` — the grain being
the dimensions the calculation can legally be grouped by.

### Promoting a calculation

A calculation is scoped to one dashboard, so it cannot pollute the shared
namespace. When the same one appears in several dashboards, that is the signal
to promote it into the model — see
[`semantic-model.md`](./semantic-model.md#promoting-a-dashboard-calculation).
