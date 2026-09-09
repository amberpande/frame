"""Everything that must be true before a single row is read.

Each rejection carries a machine-readable `reason` so the agent's planner can
act on it and retry, rather than receiving prose it has to guess at. This is
what turns one-shot generation into a converging loop.
"""

from __future__ import annotations

from typing import Any

from frame.identity import Identity
from frame.semantic.model import SemanticModel
from frame.spec.schema import QuerySpec


class GuardError(Exception):
    def __init__(self, reason: str, detail: str, **context: Any) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail
        self.context = context

    def to_dict(self) -> dict[str, Any]:
        return {"reason": self.reason, "detail": self.detail, **self.context}


def guard(
    model: SemanticModel,
    query: QuerySpec,
    identity: Identity,
    *,
    row_cap: int,
    large_table_rows: int = 50_000_000,
) -> None:
    for name in query.metrics:
        if not model.has_metric(name):
            raise GuardError(
                "unknown_metric",
                f"{name!r} is not a metric in model {model.name!r}",
                metric=name,
                available=[m.name for m in model.metrics],
            )
        if not identity.may_read(name):
            raise GuardError(
                "metric_forbidden",
                f"this identity may not read {name!r}",
                metric=name,
            )

    for name in query.by:
        if not model.has_dimension(name):
            raise GuardError(
                "unknown_dimension",
                f"{name!r} is not a dimension in model {model.name!r}",
                dimension=name,
                available=[d.name for d in model.dimensions],
            )

    # Slicing a metric by a dimension it was never grained on is the classic
    # silently-wrong answer. Here it is a rejection instead.
    for metric_name in query.metrics:
        allowed = model.effective_grain(metric_name)
        for dim in query.by:
            if dim not in allowed:
                raise GuardError(
                    "grain_violation",
                    f"metric {metric_name!r} is not grained on {dim!r}; "
                    f"it can be sliced by {sorted(allowed)}",
                    metric=metric_name,
                    dimension=dim,
                    allowed=sorted(allowed),
                )

    for clause in query.filters:
        if not (model.has_dimension(clause.field) or model.has_metric(clause.field)):
            raise GuardError(
                "unknown_filter_field",
                f"cannot filter on {clause.field!r}: not in model {model.name!r}",
                field=clause.field,
            )

    if query.order and not (
        model.has_metric(query.order.by) or query.order.by in query.by
    ):
        raise GuardError(
            "unknown_sort_field",
            f"cannot sort by {query.order.by!r}: not a selected dimension or a known metric",
            field=query.order.by,
        )

    if query.limit is not None and query.limit > row_cap:
        raise GuardError(
            "limit_exceeds_cap",
            f"limit {query.limit} exceeds the platform cap of {row_cap}",
            limit=query.limit,
            cap=row_cap,
        )

    # Against an unmodelled warehouse the likeliest expensive mistake is a
    # dashboard pointed at a very large table with nothing to prune on. A
    # source with a time column is always pruned by the compiler; one without
    # is only safe if the query filters it down itself.
    for metric_name in query.metrics:
        for base in model.base_metrics(metric_name):
            if not base.source:
                continue
            source = model.sources[base.source]
            if source.time_column or not source.row_estimate:
                continue
            if source.row_estimate > large_table_rows and not query.filters:
                raise GuardError(
                    "large_unfiltered_scan",
                    f"source {source.name!r} has no time column and about "
                    f"{source.row_estimate:,} rows, so this query would scan all of "
                    "it. Add a filter, or model a time column on the source.",
                    source=source.name,
                    rows=source.row_estimate,
                    threshold=large_table_rows,
                )

    # Refuse, do not throttle: an expensive metric asked for without any
    # grouping is almost always a mistake that would scan the whole fact table.
    expensive = [
        m for m in query.metrics if model.metric(m).cost_class == "expensive"
    ]
    if expensive and not query.by and query.limit is None:
        raise GuardError(
            "unbounded_expensive_query",
            f"metrics {expensive} are cost_class=expensive and need a `by` or a `limit`",
            metrics=expensive,
        )
