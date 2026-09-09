---
applyTo: "backend/models/**/*.yml"
---

# Editing the semantic model

This file is the platform's entire vocabulary. The compiler turns it into SQL,
and the agent may reference nothing outside it. Full guide:
[`docs/semantic-model.md`](../../docs/semantic-model.md).

## Rules

- A metric with `curated: true` **requires** `owner` and at least one entry in
  `tests`. The model refuses to load otherwise.
- A generated draft may use `curated: false` with neither. That is legal and
  intentional — it works immediately and is honest about not being reviewed.
- **Ratios are `kind: derived`**, never a second `agg`:
  `expr: "{a} / NULLIF({b}, 0)"`.
- `grain` lists the dimensions a measure may be sliced by. It is enforced;
  omitting a dimension there makes it un-sliceable, which is usually correct.
- `direction` decides whether a delta renders as good or bad. Set it.
- `approx: true` only applies to `agg: count_distinct`.
- `filters` are raw SQL fragments and are model-authored only — never built
  from user input.
- Top-level keys starting with `x-` are stripped before validation, so YAML
  anchors can host a shared grain list. Every other unknown key is an error.

## Adding a measure

```yaml
  - name: exception.p1_count          # <entity>.<thing>, dotted
    label: P1 exceptions
    kind: measure
    source: fct_exception             # a key under `sources`
    agg: count_distinct               # sum|avg|min|max|count|count_distinct
    column: exception_id
    filters: ["status IN ('OPEN','PENDING')", "priority = 'P1'"]
    grain: *exception_grain
    format: { style: integer }
    owner: fin-ops-platform           # required when curated
    tests: [non_negative]             # required when curated
    direction: lower_is_better
    synonyms: [P1, critical, urgent]  # the agent reads these
```

## Adding a derived metric

```yaml
  - name: exception.resolution_rate
    kind: derived
    expr: "{exception.closed_count} / NULLIF({exception.closed_count} + {exception.count}, 0)"
    format: { style: percent, precision: 1 }
    direction: higher_is_better
    owner: fin-ops-platform
    tests: [between_zero_and_one]
```

Anomaly metrics need a `baseline` on the underlying measure, which publishes
`{metric@avg_28d}` and `{metric@stddev_28d}`.

## After editing

The model fingerprint changes, which invalidates every cached result computed
under the old definitions. That is intended. Verify it still loads:

```bash
cd backend && python -c "from frame.semantic import get_model; print(get_model('finance_ops').fingerprint())"
python -m pytest -q
```
