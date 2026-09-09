---
applyTo: "backend/specs/**/*.json"
---

# Editing a dashboard spec

A spec is a dashboard. It is data, not code. Full procedure:
[`docs/authoring-specs.md`](../../docs/authoring-specs.md).

## Required shape

```json
{
  "$schema": "../schemas/spec.schema.json",
  "id": "matches-the-filename",
  "specVersion": 1,
  "model": "finance_ops",
  "title": "Human readable",
  "freshness": "daily",
  "params": [],
  "blocks": []
}
```

## Rules

- **No SQL.** There is no field for it, and adding one is wrong.
- **`id` must equal the filename** without `.json`.
- Every metric and dimension name must exist in the model named by `model`.
  Check `backend/models/<model>.yml` or `GET /api/v1/models/<model>`.
- Every dimension in a block's `by` must be inside **every** requested metric's
  `grain`.
- Blocks sit on a **12-column** grid. `at.x + at.w <= 12`. Do not overlap
  blocks — check `y` and `h` against neighbours.
- `compare` must reference a param declared in `params` (`"$compare_to"`).
- Declare a date param named `as_of` whenever any block has a query.
- `freshness: "live"` requires a written `justification`.

## Choosing `viz`

| Situation | Use |
|---|---|
| One headline figure | `big.number` |
| Two dates compared by category | `mark.dumbbell` |
| Many dates — a real series | `mark.line` **plus `windowDays`, no `compare`** |
| Ranked magnitude | `mark.bar` |
| Two dimensions at once | `mark.matrix` (`by` has 2 dims) |
| Exact values, several metrics | `table.grid` |
| Written summary at the top | `briefing.band` |
| "Why did this move" | `panel.explain` (has `source`, no `query`) |

Never use `mark.line` for exactly two dates.

## Cross-filtering

Give a block `source` **alongside** its own `query`:

```json
"source": { "block": "driver-block-id", "on": "select" }
```

The named block must exist. A block cannot source from itself.

## Before finishing

Validate every block query — it reads no data:

```bash
curl -s -X POST localhost:8000/api/v1/validate -H "Content-Type: application/json" \
  -d '{"model":"finance_ops","query":{ ... }}'
```

Fix any `reason` returned; the error names what is allowed.
