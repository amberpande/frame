---
mode: agent
description: Build a dashboard from a Snowflake table or view by reading its definition — model the columns, then generate and validate a spec.
---

# Build a dashboard from a table or view

You are given the name of a Snowflake table or view. Produce a working
dashboard: a semantic model entry for it, and a validated spec.

Do not write SQL. Do not invent metric names. Work in the order below.

---

## Step 1 — Read the definition

```bash
cd backend
python -m frame.introspect --describe <TABLE_OR_VIEW> \
  --database <DB> --schema <SCHEMA>
```

This prints, in one report: row count, the time column and its range, every
column with its type, an approximate distinct count, sample values, a suggested
role — and, **if it is a view, the SQL it is defined by.**

**Read the view SQL properly. It is the most valuable thing in the report.**
Column types tell you the shape of the data; the view's SQL tells you what the
business means by it.

| In the definition | Becomes |
|---|---|
| `WHERE status IN ('OPEN','PENDING')` | a `filters:` entry on the measure — the rule for what counts |
| `CASE WHEN age_days > 30 THEN 'Over 30 days' ...` | a dimension; the buckets are already named for you |
| `CASE WHEN amount > 50000 THEN TRUE` | a boolean dimension — a flag someone decided mattered |
| A join to a dimension table | the view is already denormalised; model the view, not its sources |
| `SUM(x) ... GROUP BY` | the view is pre-aggregated. Its grain is the `GROUP BY` list, and **nothing else** |

That last row is the one that causes silent wrongness. If the relation is
pre-aggregated, its `grain:` must be exactly the `GROUP BY` columns. Slicing it
any other way produces a number that looks fine and is not.

If the report says **"time column: none"**, the relation cannot be compared
across dates or charted as a series. Say so, and build a point-in-time
dashboard instead of pretending otherwise.

---

## Step 2 — Write the model entry

Generate a draft, then edit it down:

```bash
python -m frame.introspect --database <DB> --schema <SCHEMA> \
  --tables <TABLE_OR_VIEW> --name <model_name> --out models/<model_name>.yml
```

Everything comes out `curated: false`, which is legal and works immediately.
Now improve it using what you learned in step 1:

1. **Delete the noise.** Introspection is generous. A 40-column relation yields
   ~30 definitions and you probably want six. This is the highest-value edit.
2. **Add the business rules** from the view's `WHERE` as `filters:` on the
   measures. Introspection cannot know them; you just read them.
3. **Fix the grain** if the relation is pre-aggregated.
4. **Check the flagged aggregates.** Anything with a `note` about an ambiguous
   aggregate needs a decision — summing effort is meaningful, summing an age is
   not.
5. **Set `direction`** on every metric you keep (`higher_is_better`,
   `lower_is_better`, `neutral`). It decides whether a change renders as good
   or bad.
6. **Add `synonyms`** — the informal words people use. They are what lets an
   agent resolve a request to a metric later.

Leave `curated: false` unless you have a real owner and a real test. A false
claim of review is worse than an honest draft.

Verify it loads:

```bash
python -c "from frame.semantic import get_model; m=get_model('<model_name>'); print(len(m.metrics),'metrics')"
```

---

## Step 3 — Design the dashboard

Decide what question the page answers before choosing marks. Then follow
[`docs/authoring-specs.md`](../../docs/authoring-specs.md) exactly.

A sound default layout, when the relation has a time column:

| Row | Blocks |
|---|---|
| 1 | `briefing.band` across all 12 columns — lead with the written answer |
| 2 | three or four `big.number` tiles for the headline measures |
| 3 | `mark.line` for the trend (needs `windowDays`, and no `compare`) |
| 4 | `mark.dumbbell` for what moved between the two dates, `limit` 10–12 |
| 5 | `mark.matrix` for the two most useful dimensions, or `mark.bar` |
| 6 | `table.grid` for the detail |

Without a time column: drop rows 1, 3 and 4, and lead with bars and a table.

**The mistake to avoid:** `mark.line` for a two-date comparison. Two
observations are not a trend — a line asserts a path nobody measured. Use
`mark.dumbbell`.

---

## Step 4 — Validate every block before publishing

```bash
curl -s -X POST localhost:8000/api/v1/validate \
  -H "Content-Type: application/json" \
  -d '{"model":"<model_name>","query":{ ...the block query... }}'
```

Reads no data. A failure returns a `reason` code naming what is allowed —
`grain_violation` lists the legal dimensions, `unknown_metric` lists the
available names. Fix and retry until every block returns `ok: true`.

If you need a ratio that does not exist as a metric, do **not** add a measure
for it. Add a calculation to the spec:

```bash
curl -s -X POST localhost:8000/api/v1/expressions/validate \
  -H "Content-Type: application/json" \
  -d '{"model":"<model_name>","expr":"{a.value} / NULLIF({a.count}, 0)"}'
```

---

## Step 5 — Publish and confirm it renders

Write `backend/specs/<id>.json` with `"$schema": "../schemas/spec.schema.json"`,
then check two blocks actually return rows:

```bash
curl -s -X POST localhost:8000/api/v1/specs/<id>/blocks/<block>/data \
  -H "Content-Type: application/json" -d '{"params":{}}'
```

---

## Report back

State:

- which relation you read, and whether it was a table or a view
- **what you learned from the view definition** that the column types alone
  would not have told you — the filters, the buckets, the grain
- what you deleted from the generated model and why
- any aggregate you were unsure about
- any block a guard refused, and how you changed it

## Constraints

- No SQL in a spec. Ever.
- Only metrics and dimensions that exist in the model, or `calc.*` in the spec.
- Every `by` dimension must be inside every selected metric's `grain`.
- `mark.line` needs `windowDays` and must not set `compare`.
- Sorting a signed metric such as a severity needs `"abs": true`.
- `freshness: "live"` requires a written `justification`.
