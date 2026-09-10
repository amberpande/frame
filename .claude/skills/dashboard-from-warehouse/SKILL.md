---
name: dashboard-from-warehouse
description: Build a Frame dashboard from a Snowflake table or view by reading its definition. Use when asked to create a dashboard for a warehouse relation, to model a table or view into the semantic layer, or when someone names a Snowflake table and wants to see it on a page. Reads the view's SQL to recover the business rules that column types cannot show, then generates a semantic model entry and a validated spec.
---

# Dashboard from a warehouse relation

Given a Snowflake table or view, produce a semantic model entry and a working
dashboard spec.

Never write SQL. Never invent metric names. Work in this order.

## 1. Read the definition

```bash
cd backend
python -m frame.introspect --describe <TABLE_OR_VIEW> --database <DB> --schema <SCHEMA>
```

One report: row count, time column and its range, every column with type,
approximate distinct count, sample values and a suggested role — plus, for a
view, **the SQL it is defined by**.

**The view SQL is the point.** Column types say what shape the data is; the
view's SQL says what the business means by it.

- `WHERE ...` → the rule for what counts. Becomes `filters:` on the measure.
- `CASE WHEN ... THEN 'label'` → a dimension, with its buckets already named.
- `GROUP BY ...` → the relation is pre-aggregated. Its `grain:` is **exactly**
  that list. Slicing it any other way returns a plausible wrong number, which
  is the failure this whole layer exists to prevent.
- A join → the view is already denormalised. Model the view, not its sources.

"time column: none" means no comparisons and no series. Say so rather than
pretending.

## 2. Model it

```bash
python -m frame.introspect --database <DB> --schema <SCHEMA> \
  --tables <TABLE_OR_VIEW> --name <model> --out models/<model>.yml
```

Output is `curated: false` and works immediately. Then: delete the noise
(highest-value edit), add the `filters:` you read from the view, fix the grain
if pre-aggregated, resolve any flagged ambiguous aggregate, set `direction` on
everything you keep, add `synonyms`. Leave `curated: false` unless there is a
real owner and a real test.

## 3. Build the spec

Follow `docs/authoring-specs.md`. Default layout when there is a time column:
briefing band, KPI tiles, a line for the trend (`windowDays`, no `compare`), a
dumbbell for what moved, a matrix or bar, a detail table. Without a time
column, drop the trend and the dumbbell.

Never use `mark.line` for two dates. Two observations are not a trend.

## 4. Validate before publishing

`POST /api/v1/validate` per block — reads no data, and a refusal names what
would be allowed. For a ratio that is not a metric, add a spec-level `calc.*`
and check it with `POST /api/v1/expressions/validate`.

## 5. Publish and confirm

Write `backend/specs/<id>.json` including
`"$schema": "../schemas/spec.schema.json"`, then fetch two blocks' data to
confirm rows come back.

## Report

Say what you learned from the view definition that the column types alone would
not have told you, what you deleted from the generated model, any aggregate you
were unsure about, and any guard that refused a block.

## Reference

- `docs/authoring-specs.md` — the complete spec procedure
- `docs/semantic-model.md` — modelling and curation
- `.github/prompts/dashboard-from-warehouse.prompt.md` — the same procedure for
  GitHub Copilot; keep the two in step
