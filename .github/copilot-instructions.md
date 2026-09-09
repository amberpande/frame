# Copilot instructions — Frame

Repository-wide guidance. Applies to every request in this repo.

## The one-sentence model

Frame renders dashboards from **JSON specs** over a **governed semantic layer**
on Snowflake. There is one React runtime. A dashboard is a row, not a
repository — adding one is a file, never a deploy.

## Never do these

- **Never write SQL** in a spec, a React component, or anywhere outside
  `backend/frame/compile/compiler.py`. That file is the only SQL writer in the
  system, and cost governance, row-level security and cache correctness all
  depend on it staying that way.
- **Never invent a metric or dimension name.** They come from
  `backend/models/*.yml` or `GET /api/v1/models/{name}`.
- **Never delete or weaken a guard** in `backend/frame/compile/guard.py` to
  make a query pass. A refusal is designed behaviour.
- **Never bypass `frame.serve.tiers.serve()`** to reach the warehouse.
- **Never hand-edit** `backend/schemas/spec.schema.json` — regenerate with
  `python scripts/gen_schema.py`.

## Always do these

- Read `AGENTS.md` first for task routing.
- When creating a dashboard, follow `docs/authoring-specs.md` step by step.
- Include `"$schema": "../schemas/spec.schema.json"` at the top of every spec.
- Validate queries with `POST /api/v1/validate` before publishing — it reads no
  data and returns a machine-readable `reason` on failure.
- Keep `python -m pytest -q` green and `npm run typecheck` clean.

## Layout

```
backend/models/*.yml     the semantic model — metrics, dimensions, grain
backend/specs/*.json     dashboards, as rows
backend/frame/compile/   the only SQL writer, plus the guards
backend/frame/serve/     result cache, tiers, warehouse engines
backend/frame/api/       11 routes under /api/v1
frontend/src/viz/        manifests (metadata) + marks (components)
frontend/src/runtime/    SpecRenderer, BlockHost, data fetching, selection
docs/                    authoring-specs, semantic-model, snowflake-live
```

## Vocabulary

| Term | Means |
|---|---|
| **spec** | A dashboard, as JSON. `backend/specs/<id>.json`. |
| **block** | One tile in a spec: a `viz`, a placement `at`, and usually a `query`. |
| **model** | The semantic layer: metrics, dimensions, grain. |
| **metric** | A named measure or derived expression. Never raw SQL in a spec. |
| **grain** | The dimensions a metric may legally be sliced by. Enforced. |
| **plan** | Compiled SQL + bound params + cache key + cost estimate. |
| **tier** | Which layer answered: `result-cache` or `warehouse`. |
| **curated** | A definition a human has reviewed. `false` means introspected draft. |

## Frequent mistakes

1. Using `mark.line` for a two-date comparison. Two observations are not a
   trend — use `mark.dumbbell`.
2. Forgetting `windowDays` on a block whose `by` contains a time dimension. The
   query returns one row.
3. Slicing a metric by a dimension outside its `grain`. Check
   `metrics[].grain` in the model payload.
4. Putting `compare` on a time-series block. It is refused.
5. Sorting a signed metric without `"abs": true`, which buries large
   improvements.
6. Filtering on a metric. `filters[].field` must be a dimension.
7. Writing a bare column name in a calculated metric's formula. Only
   `{metric.name}` references are allowed — `amount_usd` is refused, because it
   would be a column reference escaping the semantic layer. A calculation that
   genuinely needs a column is a **measure**, and belongs in the model.
