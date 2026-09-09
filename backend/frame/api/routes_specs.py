from __future__ import annotations

from fastapi import APIRouter, HTTPException

from frame.registry import registry
from frame.semantic import get_model
from frame.spec.schema import DashboardSpec

router = APIRouter(prefix="/api/v1/specs", tags=["specs"])


@router.get("")
def index() -> list[dict]:
    return registry.list()


@router.get("/{spec_id}")
def detail(spec_id: str) -> dict:
    try:
        spec = registry.get(spec_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"no spec {spec_id!r}") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return spec.model_dump(mode="json", by_alias=True, exclude_none=True)


@router.put("/{spec_id}")
def upsert(spec_id: str, spec: DashboardSpec) -> dict:
    """Publishing a dashboard is a write to a table. No build, no deploy."""
    if spec.id != spec_id:
        raise HTTPException(
            status_code=422, detail=f"body id {spec.id!r} does not match path {spec_id!r}"
        )
    try:
        model = get_model(spec.model)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    # Validate every block against the semantic model at publish time, so a
    # broken spec is rejected here rather than discovered by a viewer.
    for block in spec.blocks:
        if not block.query:
            continue
        for metric in block.query.metrics:
            if not model.has_metric(metric):
                raise HTTPException(
                    status_code=422,
                    detail=f"block {block.id!r}: unknown metric {metric!r}",
                )
        for dim in block.query.by:
            if not model.has_dimension(dim):
                raise HTTPException(
                    status_code=422,
                    detail=f"block {block.id!r}: unknown dimension {dim!r}",
                )

    registry.put(spec)
    return spec.model_dump(mode="json", by_alias=True, exclude_none=True)


@router.delete("/{spec_id}")
def remove(spec_id: str) -> dict:
    registry.delete(spec_id)
    return {"deleted": spec_id}
