---
mode: agent
description: Create a new Frame dashboard spec from a request, validated end to end.
---

# Create a dashboard spec

Create a new dashboard in `backend/specs/`. Do not write SQL anywhere.

## Procedure — follow in order

**1. Read the model.** Run:

```bash
curl -s localhost:8000/api/v1/models/finance_ops
```

If the API is not running, read `backend/models/*.yml` directly. Collect the
real `metrics[].name`, each one's `grain`, and the `dimensions[].name`. Note
which dimensions have `"kind": "time"`.

Never use a name that is not in that list.

**2. Decide the blocks.** For the question being asked, choose marks from
`frontend/src/viz/manifests.ts`. Respect each manifest's `notFor`. In
particular: two dates compared by category is `mark.dumbbell`, never
`mark.line`.

**3. Write the file** at `backend/specs/<id>.json`, where `<id>` matches the
filename. Start with:

```json
{
  "$schema": "../schemas/spec.schema.json",
  "id": "<id>",
  "specVersion": 1,
  "model": "<model>",
  "title": "...",
  "description": "...",
  "freshness": "daily",
  "owner": "...",
  "params": [
    { "name": "as_of", "type": "date", "label": "As of", "default": "@latest_close" },
    { "name": "compare_to", "type": "date", "label": "Compared to", "default": "@as_of - 7d" }
  ],
  "blocks": []
}
```

Lay blocks out on a 12-column grid, row height 62 px. `at.x + at.w <= 12`, and
no two blocks may overlap.

**4. Validate every block's query** before publishing:

```bash
curl -s -X POST localhost:8000/api/v1/validate \
  -H "Content-Type: application/json" \
  -d '{"model":"<model>","query":{ ...the block query... }}'
```

If `ok` is false, read the `reason` and fix it. The error names what is
allowed. Repeat until every block validates.

**5. Confirm it renders**, for at least two blocks:

```bash
curl -s -X POST localhost:8000/api/v1/specs/<id>/blocks/<block>/data \
  -H "Content-Type: application/json" -d '{"params":{}}'
```

**6. Report** the file path, the blocks created, and any query you had to
change because a guard refused it.

## Constraints

- No SQL in the spec.
- Every `by` dimension must be inside every requested metric's `grain`.
- `mark.line` needs `windowDays` and must not set `compare`.
- Sorting a signed metric such as `severity.signed_z` needs `"abs": true`.
- `freshness: "live"` requires a `justification`.

## Reference

- Full procedure: `docs/authoring-specs.md`
- Existing examples: `backend/specs/ops-control-tower.json` (breadth),
  `vendor-risk.json` (cross-filtering), `sla-scorecard.json` (two sources)
