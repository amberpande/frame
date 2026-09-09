"""L2 — the query compiler.

Turns a spec's `query` object into SQL. This is the only component in the
platform that writes SQL: the builder cannot, the agent cannot, and no spec may
carry a SQL string. That constraint is what makes cost governance, row-level
security, cache correctness and reproducibility enforceable in one place.

Shape of the emitted statement, when a comparison and a baseline are involved:

    WITH obs   AS (aggregate at the as-of date)
       , cmp   AS (the same aggregate at the comparison date)
       , hist  AS (daily aggregate over the baseline window)
       , base  AS (rolling stats per group from hist)
       , cur   AS (obs LEFT JOIN base, derived metrics evaluated)
       , prv   AS (cmp LEFT JOIN base, derived metrics evaluated)
       , ranked AS (ROW_NUMBER over cur by the requested sort)
    SELECT 'current' ... FROM cur JOIN ranked
    UNION ALL
    SELECT 'compare' ... FROM prv JOIN ranked

The ranking CTE matters: `limit` selects top-N *groups*, then both observations
of each are returned. Limiting rows instead would truncate one side of a
comparison and silently misstate every variance on the page.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from frame.compile.dialects import Dialect
from frame.compile.guard import GuardError, guard
from frame.compile.plan import ColumnMeta, CostEstimate, QueryPlan
from frame.identity import Identity
from frame.semantic.model import METRIC_REF, Metric, SemanticModel
from frame.spec.schema import FilterClause, QuerySpec

_OPS = {
    "eq": "=",
    "ne": "<>",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
}


@dataclass
class CompileRequest:
    model: SemanticModel
    query: QuerySpec
    as_of: date
    identity: Identity
    dialect: Dialect
    compare_to: date | None = None
    row_cap: int = 50_000
    large_table_rows: int = 50_000_000


def compile_query(req: CompileRequest) -> QueryPlan:
    model, q, d = req.model, req.query, req.dialect
    guard(model, q, req.identity, row_cap=req.row_cap,
          large_table_rows=req.large_table_rows)

    # -- resolve what actually has to be read ------------------------------
    output_metrics = list(q.metrics)
    work_metrics = list(q.metrics)
    if q.order and model.has_metric(q.order.by) and q.order.by not in work_metrics:
        work_metrics.append(q.order.by)  # sortable without being displayed

    base_measures: list[Metric] = []
    for name in work_metrics:
        for measure in model.base_metrics(name):
            if measure.name not in {b.name for b in base_measures}:
                base_measures.append(measure)

    source_names = {m.source for m in base_measures if m.source}
    if len(source_names) > 1:
        raise GuardError(
            "multi_source_query",
            "this query spans several sources; declared join paths are not "
            "supported yet, so split it into one block per source",
            sources=sorted(source_names),
        )
    source = model.sources[next(iter(source_names))]
    relation = d.relation(source)
    # Optional. A dimension table or a snapshot has no date, and asking for
    # "as of" against one is meaningless rather than an error — it is only an
    # error when the query actually needs a time axis.
    time_col = d.column(source.time_column) if source.time_column else None

    def require_time(what: str) -> None:
        if time_col is None:
            raise GuardError(
                "no_time_column",
                f"source {source.name!r} declares no time_column, so it cannot "
                f"support {what}",
                source=source.name,
                needed_for=what,
            )

    dims = [model.dimension(name) for name in q.by]
    dim_alias = {dim.name: f"d{i}" for i, dim in enumerate(dims)}
    meas_alias = {m.name: f"m{i}" for i, m in enumerate(base_measures)}

    # -- baseline statistics -----------------------------------------------
    needed_stats: set[tuple[str, str]] = set()
    for name in work_metrics:
        for ref, stat in model.metric(name).references():
            if stat:
                needed_stats.add((ref, stat))
    window_days = max(
        (
            model.metric(ref).baseline.window_days
            for ref, _ in needed_stats
            if model.metric(ref).baseline
        ),
        default=0,
    )
    use_baseline = bool(needed_stats) and window_days > 0
    if use_baseline:
        require_time("a rolling baseline")
    if req.compare_to is not None:
        require_time("a comparison period")

    # -- point-in-time, or a series? ---------------------------------------
    # Grouping by a time dimension means the query wants a range. Leaving the
    # as-of equality in place would return exactly one date and quietly draw a
    # one-point line, so the two modes are separated explicitly.
    series_dims = [dim for dim in dims if dim.kind == "time"]
    is_series = bool(series_dims)

    if is_series:
        require_time("a time series")
        if len(series_dims) > 1:
            raise GuardError(
                "multiple_time_dimensions",
                f"a series can have one time axis; got {[d.name for d in series_dims]}",
                dimensions=[d.name for d in series_dims],
            )
        if req.compare_to is not None:
            raise GuardError(
                "compare_with_time_series",
                "a time series already shows the change over time; adding a "
                "comparison period would return two observations for every "
                "point. Drop `compare`, or drop the time dimension from `by`.",
                dimension=series_dims[0].name,
            )
        if needed_stats:
            raise GuardError(
                "baseline_with_time_series",
                f"metrics with a rolling baseline ({sorted({r for r, _ in needed_stats})}) "
                "compare one date against its own recent normal, which is not "
                "defined per point in a series. Chart the base metric instead.",
                metrics=sorted({r for r, _ in needed_stats}),
            )

    series_window = (q.window_days or 90) if is_series else 0

    # -- parameter binding --------------------------------------------------
    params: dict[str, Any] = {}

    def bind(value: Any) -> str:
        key = f"p{len(params)}"
        params[key] = value
        return d.placeholder(key)

    # -- WHERE construction -------------------------------------------------
    def spec_filters() -> list[str]:
        out: list[str] = []
        for clause in q.filters:
            if model.has_metric(clause.field):
                raise GuardError(
                    "metric_filter_unsupported",
                    f"cannot filter on metric {clause.field!r}; filter on a "
                    "dimension, or sort and limit instead",
                    field=clause.field,
                )
            col = d.column(model.dimension(clause.field).column)
            if clause.op in _OPS:
                out.append(f"{col} {_OPS[clause.op]} {bind(clause.value)}")
            elif clause.op in {"in", "not_in"}:
                values = clause.value if isinstance(clause.value, list) else [clause.value]
                if not values:
                    out.append("1=0" if clause.op == "in" else "1=1")
                    continue
                placeholders = ", ".join(bind(v) for v in values)
                keyword = "IN" if clause.op == "in" else "NOT IN"
                out.append(f"{col} {keyword} ({placeholders})")
            elif clause.op == "contains":
                out.append(f"{col} LIKE {bind(f'%{clause.value}%')}")
        return out

    static_predicates = list(req.identity.row_predicates) + spec_filters()

    def where_for(clauses: list[str]) -> str:
        parts = clauses + static_predicates
        return " AND ".join(f"({p})" for p in parts) if parts else "1=1"

    # -- aggregate expressions ---------------------------------------------
    def agg_expr(m: Metric) -> str:
        cond = " AND ".join(f"({f})" for f in m.filters)
        if m.agg == "count":
            return f"SUM(CASE WHEN {cond} THEN 1 ELSE 0 END)" if cond else "COUNT(*)"
        col = d.column(m.column or "")
        inner = f"CASE WHEN {cond} THEN {col} END" if cond else col
        if m.agg == "count_distinct":
            # HyperLogLog where the model opts in: typically within a fraction
            # of a percent, and dramatically cheaper on a wide table.
            return f"APPROX_COUNT_DISTINCT({inner})" if m.approx else f"COUNT(DISTINCT {inner})"
        return f"{(m.agg or '').upper()}({inner})"

    dim_select = [f"{d.column(dim.column)} AS {dim_alias[dim.name]}" for dim in dims]
    meas_select = [f"{agg_expr(m)} AS {meas_alias[m.name]}" for m in base_measures]

    def period_cte(name: str, when: date) -> str:
        cols = ",\n         ".join(dim_select + meas_select)
        group = (
            f"\n  GROUP BY {', '.join(str(i + 1) for i in range(len(dims)))}" if dims else ""
        )
        if time_col is None:
            time_clauses = []
        elif is_series:
            start = when - timedelta(days=series_window)
            time_clauses = [
                f"{time_col} > {bind(start)}",
                f"{time_col} <= {bind(when)}",
            ]
        else:
            time_clauses = [f"{time_col} = {bind(when)}"]
        return (
            f"{name} AS (\n"
            f"  SELECT {cols}\n"
            f"  FROM {relation}\n"
            f"  WHERE {where_for(time_clauses)}"
            f"{group}\n)"
        )

    ctes: list[str] = [period_cte("obs", req.as_of)]
    if req.compare_to is not None:
        ctes.append(period_cte("cmp", req.compare_to))

    if use_baseline:
        window_start = req.as_of - timedelta(days=window_days)
        hist_cols = ",\n         ".join(
            [f"{time_col} AS __d"] + dim_select + meas_select
        )
        hist_group = ", ".join(str(i + 1) for i in range(1 + len(dims)))
        ctes.append(
            "hist AS (\n"
            f"  SELECT {hist_cols}\n"
            f"  FROM {relation}\n"
            "  WHERE "
            + where_for(
                [f"{time_col} >= {bind(window_start)}", f"{time_col} < {bind(req.as_of)}"]
            )
            + f"\n  GROUP BY {hist_group}\n)"
        )
        stat_cols: list[str] = []
        for ref, stat in sorted(needed_stats):
            alias = meas_alias[ref]
            kind = stat.rsplit("_", 1)[0]
            inner = f"h.{alias}"
            fn = d.stddev(inner) if kind == "stddev" else f"{kind.upper()}({inner})"
            stat_cols.append(f"{fn} AS {alias}_{stat}")
        base_dims = [f"h.{dim_alias[dim.name]}" for dim in dims]
        base_group = (
            f"\n  GROUP BY {', '.join(str(i + 1) for i in range(len(dims)))}" if dims else ""
        )
        ctes.append(
            "base AS (\n"
            f"  SELECT {', '.join(base_dims + stat_cols)}\n"
            "  FROM hist h"
            f"{base_group}\n)"
        )

    # -- projection of requested metrics ------------------------------------
    def project(metric_name: str) -> str:
        metric = model.metric(metric_name)
        if metric.kind == "measure":
            return f"o.{meas_alias[metric_name]}"

        def repl(match: Any) -> str:
            ref, stat = match.group(1), match.group(2)
            if stat:
                return f"b.{meas_alias[ref]}_{stat}"
            return f"o.{meas_alias[ref]}"

        return f"({METRIC_REF.sub(repl, metric.expr or '')})"

    value_alias = {name: f"v{i}" for i, name in enumerate(work_metrics)}

    def projected_cte(name: str, from_cte: str) -> str:
        cols = [f"o.{dim_alias[dim.name]}" for dim in dims]
        cols += [f"{project(m)} AS {value_alias[m]}" for m in work_metrics]
        join = ""
        if use_baseline:
            if dims:
                on = " AND ".join(
                    f"o.{dim_alias[dim.name]} = b.{dim_alias[dim.name]}" for dim in dims
                )
            else:
                on = "1=1"
            join = f"\n  LEFT JOIN base b ON {on}"
        return (
            f"{name} AS (\n"
            f"  SELECT {', '.join(cols)}\n"
            f"  FROM {from_cte} o{join}\n)"
        )

    ctes.append(projected_cte("cur", "obs"))
    if req.compare_to is not None:
        ctes.append(projected_cte("prv", "cmp"))

    # -- ranking ------------------------------------------------------------
    effective_limit = min(q.limit or req.row_cap, req.row_cap)

    if dims:
        if q.order:
            target = (
                value_alias[q.order.by]
                if q.order.by in value_alias
                else dim_alias[q.order.by]
            )
            expr = f"ABS({target})" if q.order.abs else target
            order_sql = f"{expr} {q.order.dir.upper()} NULLS LAST"
        else:
            order_sql = f"{dim_alias[dims[0].name]} ASC"
        rank_dims = ", ".join(dim_alias[dim.name] for dim in dims)
        ctes.append(
            "ranked AS (\n"
            f"  SELECT {rank_dims}, ROW_NUMBER() OVER (ORDER BY {order_sql}) AS __rank\n"
            "  FROM cur\n)"
        )

    # -- final projection ---------------------------------------------------
    def final_select(period: str, cte: str, alias: str) -> str:
        cols = [f"'{period}' AS {d.quote('__period')}"]
        if dims:
            cols.append(f"r.__rank AS {d.quote('__rank')}")
        else:
            cols.append(f"1 AS {d.quote('__rank')}")
        cols += [
            f"{alias}.{dim_alias[dim.name]} AS {d.quote(dim.name)}" for dim in dims
        ]
        cols += [
            f"{alias}.{value_alias[name]} AS {d.quote(name)}" for name in output_metrics
        ]
        sql = f"SELECT {', '.join(cols)}\nFROM {cte} {alias}"
        if dims:
            on = " AND ".join(
                f"{alias}.{dim_alias[dim.name]} = r.{dim_alias[dim.name]}" for dim in dims
            )
            sql += f"\nJOIN ranked r ON {on}\nWHERE r.__rank <= {bind(effective_limit)}"
        return sql

    body = final_select("current", "cur", "c")
    if req.compare_to is not None:
        body += "\nUNION ALL\n" + final_select("compare", "prv", "p")
    body += f"\nORDER BY {d.quote('__rank')}, {d.quote('__period')}"

    sql = "WITH " + ",\n".join(ctes) + "\n" + body

    # -- column metadata ----------------------------------------------------
    columns: list[ColumnMeta] = [
        ColumnMeta(name="__period", role="period", label="Period"),
        ColumnMeta(name="__rank", role="rank", label="Rank"),
    ]
    for dim in dims:
        columns.append(ColumnMeta(name=dim.name, role="dimension", label=dim.label))
    for name in output_metrics:
        metric = model.metric(name)
        columns.append(
            ColumnMeta(
                name=name,
                role="metric",
                label=metric.label,
                format=metric.format,
                direction=metric.direction,
            )
        )

    cost = CostEstimate(
        periods=series_window if is_series else (2 if req.compare_to is not None else 1),
        baseline_days=window_days if use_baseline else 0,
        cost_class=max(
            (model.metric(n).cost_class for n in work_metrics),
            key=["cheap", "moderate", "expensive"].index,
        ),
        row_cap=effective_limit,
    )

    return QueryPlan(
        sql=sql,
        params=params,
        columns=tuple(columns),
        dialect=d.name,
        model_name=model.name,
        model_fingerprint=model.fingerprint(),
        policy_fingerprint=req.identity.fingerprint(),
        cost=cost,
    )
