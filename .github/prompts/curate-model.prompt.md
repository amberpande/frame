---
mode: agent
description: Curate an introspected semantic model — delete noise, fix aggregates, promote definitions.
---

# Curate a draft semantic model

`python -m frame.introspect` generates definitions with `curated: false`. They
work immediately. This task turns the useful ones into reviewed definitions and
deletes the rest.

## Procedure

**1. Measure the starting point.**

```bash
curl -s localhost:8000/api/v1/models/<model>/coverage
```

Note `metrics.curated` versus `metrics.total`, and read `debt.flaggedForReview`.

**2. Delete aggressively.** Introspection is deliberately generous — a
40-column table yields ~30 definitions and you probably want six. Removing
noise is the highest-value edit. Delete a metric or dimension when:

- Nothing would ever chart it (surrogate keys, load timestamps, audit columns).
- It duplicates another definition with a worse name.
- It is a text dimension with high cardinality that nobody groups by.

**3. Fix the flagged aggregates.** Search for them:

```bash
grep -n "Aggregate inferred" backend/models/<model>.yml
```

Duration columns default to `avg`. Decide per column: summing effort is
meaningful, summing an age is not. Change `agg` if needed and delete the note.

**4. Rename to the words people use.** Then add `synonyms` for the informal
terms — the agent reads them to resolve a request to a metric.

**5. Add business rules.** Introspection cannot know that "open" means
`status IN ('OPEN','PENDING')`. Add `filters` to the measure.

**6. Set `direction`** on every metric you keep: `higher_is_better`,
`lower_is_better` or `neutral`. It decides whether a delta renders as good or
bad.

**7. Promote.** Add `owner` and at least one `tests` entry, then set
`curated: true`. The model will refuse to load if either is missing.

**8. Verify.**

```bash
cd backend
python -c "from frame.semantic import get_model; m=get_model('<model>'); print(len(m.metrics),'metrics')"
python -m pytest -q
curl -s localhost:8000/api/v1/models/<model>/coverage
```

**9. Report** the before/after curated ratio, what you deleted and why, and any
aggregate decision you were not confident about.

## Rules

- Never set `curated: true` without a real owner. A false claim of review is
  worse than an honest draft.
- Ratios are `kind: derived` over other metrics, never a second `agg`.
- Keep the model small. Eighty well-defined metrics cover most of a thousand
  dashboards; a few hundred is a signal to consolidate.
- Changing the model changes its fingerprint, which invalidates cached results.
  That is intended.

## Reference

`docs/semantic-model.md`
