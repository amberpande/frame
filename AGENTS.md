# AGENTS.md

Instructions for coding agents working in this repository. Read this before
editing anything.

## What this project is

Frame renders dashboards from JSON specs over a governed semantic layer on
Snowflake. **One React runtime; dashboards are rows, not repositories.** Adding
a dashboard is a file, not a deploy.

## Hard rules

1. **Never put SQL in a spec, a component, or the frontend.** The compiler
   (`backend/frame/compile/compiler.py`) is the only code that writes SQL. If a
   task seems to need SQL elsewhere, it needs a metric in the semantic model
   instead.
2. **Never add a code path from the API or the agent to the warehouse that
   bypasses `frame.serve.tiers.serve()`.** Cost governance, row-level security
   and cache correctness are all properties of there being one path.
3. **Never reference a metric or dimension that is not in the model.** Check
   with `GET /api/v1/models/{name}` or read `backend/models/*.yml`.
4. **Never remove a guard to make a query work.** A refusal is the designed
   behaviour. Fix the query or add the definition.
5. **Never change `specVersion` handling.** Old specs must keep rendering;
   upgraders run at read time in `backend/frame/spec/upgrade.py`.
6. **Do not hand-edit `backend/schemas/spec.schema.json`.** Regenerate it:
   `python scripts/gen_schema.py`.

## Where things live

| Task | File |
|---|---|
| Add or edit a dashboard | `backend/specs/<id>.json` |
| Add or edit a metric/dimension | `backend/models/<model>.yml` |
| Change how SQL is produced | `backend/frame/compile/compiler.py` |
| Add a validation rule | `backend/frame/compile/guard.py` |
| Add a visualization | `frontend/src/viz/manifests.ts` + `frontend/src/viz/marks/` + `registry.ts` |
| Add a chart option | An `OptionSpec` in the mark's manifest, read via `viz/options.ts` |
| Change the builder | `frontend/src/builder/` — must stay generic; no per-chart code |
| Change caching or tiers | `backend/frame/serve/` |
| Add an API route | `backend/frame/api/` |

## Documentation

| Doc | Read it when |
|---|---|
| [`docs/authoring-specs.md`](docs/authoring-specs.md) | Creating or editing a dashboard. **The complete procedure.** |
| [`docs/semantic-model.md`](docs/semantic-model.md) | Adding a metric, or bootstrapping a model from an unmodelled warehouse |
| [`docs/snowflake-live.md`](docs/snowflake-live.md) | Connecting to Snowflake, or investigating cost |
| [`docs/deployment.md`](docs/deployment.md) | Deploying on ECS, caching topology, scaling |
| [`README.md`](README.md) | Setup and the decisions worth knowing |

## Common tasks

### Create a dashboard

Follow `docs/authoring-specs.md` exactly. Summary:

1. `GET /api/v1/models/{model}` — get real metric and dimension names.
2. Write `backend/specs/<id>.json` with `"$schema": "../schemas/spec.schema.json"`.
3. Validate every block query: `POST /api/v1/validate`.
4. Confirm it renders: `POST /api/v1/specs/{id}/blocks/{block}/data`.

Do not invent metric names. Do not put SQL anywhere.

### Add a metric

Edit `backend/models/<model>.yml`. A metric with `curated: true` requires
`owner` and at least one `tests` entry, or the model refuses to load. A
generated draft may use `curated: false` with neither.

Ratios are `kind: derived` over other metrics — never a second `agg`.

### Add a visualization

1. Add a manifest to `frontend/src/viz/manifests.ts`. Fill in `notFor`
   honestly; it is the field that stops a mark being misused.
2. Add the component under `frontend/src/viz/marks/`, default-exported.
3. Register it in `frontend/src/viz/registry.ts` with
   `lazy(() => import("./marks/Yours"))`.

### Introspect an unmodelled warehouse

```bash
cd backend
python -m frame.introspect --rank-by-usage --top 25          # what is actually queried
python -m frame.introspect --schema OPS --tables A,B --name ops --out models/ops.yml
```

Everything generated is `curated: false`. That is intentional and it works
immediately; curation is a separate, incremental job.

## Verify before you finish

```bash
cd backend  && python -m pytest -q          # must stay green
cd frontend && npm run typecheck            # must stay clean
```

If you changed `backend/frame/spec/schema.py`, also run
`python scripts/gen_schema.py` and update `frontend/src/spec/types.ts` to
match — drift between those three is the bug class that eats a quarter.

## Style

- Match the surrounding code; do not introduce new patterns or libraries.
- Comments explain **why**, not what. If a line is load-bearing for a
  guarantee, say which guarantee.
- No new runtime dependencies without a clear reason.
