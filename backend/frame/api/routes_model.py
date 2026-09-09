from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from frame.api.deps import current_identity
from frame.compile.dialects import get_dialect
from frame.identity import Identity
from frame.semantic import get_model, list_models
from frame.serve import get_engine

router = APIRouter(prefix="/api/v1/models", tags=["model"])


@router.get("")
def index() -> list[dict]:
    out = []
    for name in list_models():
        model = get_model(name)
        out.append(
            {
                "name": model.name,
                "label": model.label,
                "description": model.description,
                "metrics": len(model.metrics),
                "dimensions": len(model.dimensions),
                "fingerprint": model.fingerprint(),
            }
        )
    return out


@router.get("/{name}")
def detail(name: str) -> dict:
    """The builder's palette and the agent's entire vocabulary.

    Same payload for both on purpose: whatever a human can drop, the agent can
    reference, and nothing else exists.
    """
    try:
        model = get_model(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None

    return {
        "name": model.name,
        "label": model.label,
        "description": model.description,
        "fingerprint": model.fingerprint(),
        "dimensions": [
            {
                "name": d.name,
                "label": d.label,
                "kind": d.kind,
                "synonyms": d.synonyms,
                "description": d.description,
            }
            for d in model.dimensions
        ],
        "metrics": [
            {
                "name": m.name,
                "label": m.label,
                "kind": m.kind,
                "format": m.format,
                "direction": m.direction,
                "costClass": m.cost_class,
                "owner": m.owner,
                "synonyms": m.synonyms,
                "note": m.note,
                "grain": sorted(model.effective_grain(m.name)),
                "hasBaseline": m.baseline is not None,
            }
            for m in model.metrics
        ],
    }


@router.get("/{name}/dimensions/{dimension}/values")
def dimension_values(
    name: str,
    dimension: str,
    limit: int = 200,
    identity: Identity = Depends(current_identity),
) -> list[str]:
    """Distinct values, for filter controls in the runtime and the builder.

    The identity's row predicates apply here too. Offering a value in a filter
    that the same identity cannot query would be a confusing dead end at best,
    and a disclosure at worst.
    """
    try:
        model = get_model(name)
        dim = model.dimension(dimension)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None

    engine = get_engine()
    dialect = get_dialect(engine.dialect)
    source = model.sources[dim.source]
    column = dialect.column(dim.column)

    predicates = [f"{column} IS NOT NULL", *identity.row_predicates]
    where = " AND ".join(f"({p})" for p in predicates)

    sql = (
        f"SELECT DISTINCT {column} FROM {dialect.relation(source)} "
        f"WHERE {where} ORDER BY 1 LIMIT {min(limit, 1000)}"
    )
    return [str(row[0]) for row in engine.fetch_all(sql)]


@router.get("/{name}/coverage")
def coverage(name: str) -> dict:
    """How much of this model has actually been reviewed by a human.

    Introspection writes drafts so a dashboard can be built the day the
    warehouse is connected. That is only honest if the remaining debt is
    visible, so it is reportable rather than implicit.
    """
    try:
        model = get_model(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None

    metrics = model.metrics
    dimensions = model.dimensions
    curated_metrics = [m for m in metrics if m.curated]
    unowned = [m.name for m in metrics if m.owner == "unowned"]
    untested = [m.name for m in metrics if not m.tests]
    flagged = [m.name for m in metrics if m.note and not m.curated]

    def pct(part: int, whole: int) -> float:
        return round(part / whole, 4) if whole else 1.0

    return {
        "model": model.name,
        "fingerprint": model.fingerprint(),
        "metrics": {
            "total": len(metrics),
            "curated": len(curated_metrics),
            "ratio": pct(len(curated_metrics), len(metrics)),
        },
        "dimensions": {
            "total": len(dimensions),
            "curated": sum(1 for d in dimensions if d.curated),
            "ratio": pct(sum(1 for d in dimensions if d.curated), len(dimensions)),
        },
        "sources": {
            "total": len(model.sources),
            "curated": sum(1 for s in model.sources.values() if s.curated),
            "withoutTimeColumn": [
                s.name for s in model.sources.values() if not s.time_column
            ],
        },
        "debt": {
            "unowned": unowned,
            "untested": untested,
            "flaggedForReview": flagged,
        },
    }
