from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from frame import config
from frame.api.deps import current_identity
from frame.compile import CompileRequest, GuardError, compile_query, get_dialect
from frame.compile.plan import QueryPlan
from frame.identity import Identity
from frame.params import bind_query, latest_date, param_filters, resolve_params
from frame.registry import registry
from frame.semantic import get_model
from frame.semantic.expr import ExpressionError
from frame.semantic.expr import validate_expression as validate_expr
from frame.semantic.overlay import check_single_source, overlay, source_map
from frame.serve import get_engine, serve
from frame.serve import adhoc
from frame.serve.tiers import ServedResult
from frame.spec.schema import FilterClause, Freshness, QuerySpec

router = APIRouter(prefix="/api/v1", tags=["query"])


def _envelope(plan: QueryPlan, served: ServedResult, *, explain: bool, params: dict) -> dict:
    meta: dict[str, Any] = {
        "planHash": plan.hash[:16],
        "queryTag": plan.query_tag,
        "tier": served.tier,
        "cached": served.cached,
        "elapsedMs": round(served.result.elapsed_ms, 2),
        "rowCount": served.result.row_count,
        "modelFingerprint": plan.model_fingerprint,
        "policyFingerprint": plan.policy_fingerprint,
        "cost": {
            "periods": plan.cost.periods,
            "baselineDays": plan.cost.baseline_days,
            "dayPartitions": plan.cost.scanned_day_partitions,
            "class": plan.cost.cost_class,
            "rowCap": plan.cost.row_cap,
        },
        "params": {k: (v.isoformat() if isinstance(v, date) else v) for k, v in params.items()},
    }
    if explain:
        meta["sql"] = plan.sql
        meta["bindings"] = {
            k: (v.isoformat() if isinstance(v, date) else v) for k, v in plan.params.items()
        }
    return {"columns": served.result.columns, "rows": served.result.rows, "meta": meta}


class BlockDataRequest(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)
    explain: bool = False
    # Cross-filters: what the viewer has selected in another block. They arrive
    # as structured clauses and go through the same guard as anything a spec
    # declares, so a selection cannot widen what an identity may read.
    filters: list[FilterClause] = Field(default_factory=list)


@router.post("/specs/{spec_id}/blocks/{block_id}/data")
def block_data(
    spec_id: str,
    block_id: str,
    body: BlockDataRequest,
    identity: Identity = Depends(current_identity),
) -> dict:
    """What the renderer calls. One block, one plan, one tier decision."""
    try:
        spec = registry.get(spec_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"no spec {spec_id!r}") from None

    try:
        block = spec.block(block_id)
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"spec {spec_id!r} has no block {block_id!r}"
        ) from None

    # A scratchpad block runs the viewer's own SQL, under the viewer's own
    # warehouse role. It bypasses the compiler by design, so it is never cached
    # across identities and it is tagged separately for cost attribution.
    if block.sql is not None:
        try:
            result = adhoc.run(
                get_engine(),
                block.sql.sql,
                identity,
                row_cap=config.MAX_ROWS,
                query_tag=f"frame:adhoc:{spec_id}:{block_id}",
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None
        return {
            "columns": result.columns,
            "rows": result.rows,
            "meta": {
                "planHash": "adhoc",
                "queryTag": f"frame:adhoc:{spec_id}:{block_id}",
                "tier": "warehouse",
                "cached": False,
                "governed": False,
                "elapsedMs": round(result.elapsed_ms, 2),
                "rowCount": result.row_count,
                "rowCap": config.MAX_ROWS,
                "ranAs": identity.warehouse_role,
                "params": {},
            },
        }

    if block.query is None:
        raise HTTPException(
            status_code=422,
            detail=f"block {block_id!r} has no query of its own; it reads from "
            f"{block.source.block if block.source else 'nothing'}",
        )

    # A dashboard's own calculations behave exactly like model metrics from
    # here on: same compiler, same guards, same grain rules.
    try:
        model = overlay(get_model(spec.model), spec.metrics)
    except ExpressionError as exc:
        raise HTTPException(status_code=422, detail=exc.to_dict()) from None
    engine = get_engine()

    values = resolve_params(spec, model, engine, body.params)
    query, compare_to = bind_query(block.query, values)
    query.filters = list(query.filters) + param_filters(spec, values) + list(body.filters)
    if block.sort and query.order is None:
        query.order = block.sort

    as_of = values.get("as_of")
    as_of = as_of if isinstance(as_of, date) else latest_date(model, engine)

    plan = _compile(model, query, as_of, compare_to, identity)
    served = serve(plan, spec.freshness)
    return _envelope(plan, served, explain=body.explain, params=values)


class QueryRequest(BaseModel):
    """Ad-hoc compilation for the builder's live preview and the agent's
    validator. Same compiler, same guards, same cache — there is no second
    path into the warehouse."""

    model: str
    query: QuerySpec
    as_of: date | None = None
    compare_to: date | None = None
    freshness: Freshness = Freshness.near_real_time
    explain: bool = False


@router.post("/query")
def ad_hoc(
    body: QueryRequest,
    identity: Identity = Depends(current_identity),
) -> dict:
    try:
        model = get_model(body.model)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None

    engine = get_engine()
    as_of = body.as_of or latest_date(model, engine)
    plan = _compile(model, body.query, as_of, body.compare_to, identity)
    served = serve(plan, body.freshness)
    return _envelope(plan, served, explain=body.explain, params={"as_of": as_of})


class ValidateRequest(BaseModel):
    model: str
    query: QuerySpec
    as_of: date | None = None
    compare_to: date | None = None


@router.post("/validate")
def validate(
    body: ValidateRequest,
    identity: Identity = Depends(current_identity),
) -> dict:
    """Compile without executing.

    This is the agent's loop: a rejection comes back as a structured `reason`
    the planner can act on and retry, rather than prose it has to guess at.
    Nothing is read from the warehouse to answer this.
    """
    try:
        model = get_model(body.model)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None

    try:
        plan = _compile(
            model, body.query, body.as_of or date.today(), body.compare_to, identity
        )
    except GuardError as exc:
        return {"ok": False, "error": exc.to_dict()}

    return {
        "ok": True,
        "planHash": plan.hash[:16],
        "sql": plan.sql,
        "columns": [
            {"name": c.name, "role": c.role, "label": c.label} for c in plan.columns
        ],
        "cost": {
            "periods": plan.cost.periods,
            "baselineDays": plan.cost.baseline_days,
            "dayPartitions": plan.cost.scanned_day_partitions,
            "class": plan.cost.cost_class,
            "rowCap": plan.cost.row_cap,
        },
    }


def _compile(model, query, as_of, compare_to, identity: Identity) -> QueryPlan:
    engine = get_engine()
    return compile_query(
        CompileRequest(
            model=model,
            query=query,
            as_of=as_of,
            compare_to=compare_to,
            identity=identity,
            dialect=get_dialect(engine.dialect),
            row_cap=config.MAX_ROWS,
            large_table_rows=config.LARGE_TABLE_ROWS,
        )
    )


class ExpressionRequest(BaseModel):
    model: str
    expr: str


@router.post("/expressions/validate")
def validate_expression_endpoint(body: ExpressionRequest) -> dict:
    """Check a calculated-metric formula without running anything.

    This is what the formula editor calls on every keystroke, and what an agent
    calls before writing a calculation into a spec. It reads no data.
    """
    try:
        model = get_model(body.model)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None

    known = {m.name for m in model.metrics}
    try:
        parsed = validate_expr(body.expr, known)
        check_single_source(source_map(model), parsed)
    except ExpressionError as exc:
        return {"ok": False, "error": exc.to_dict()}

    return {
        "ok": True,
        "references": list(parsed.references),
        "functions": list(parsed.functions),
        # The calculation can only be sliced where all of its inputs can be.
        "grain": sorted(
            set.intersection(*(model.effective_grain(r) for r in parsed.references))
            if parsed.references
            else set()
        ),
    }
