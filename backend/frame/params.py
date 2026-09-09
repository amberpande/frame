"""Resolving a spec's params into concrete values.

Specs declare params symbolically — `@latest_close`, `@as_of - 7d` — so the
same row means "the most recent close and the week before it" whenever it is
opened, rather than freezing a date at authoring time. Resolution happens
server-side so the client stays dumb and the agent has one fewer thing to get
wrong.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import date, datetime, timedelta
from typing import Any

from frame import config
from frame.compile.dialects import get_dialect
from frame.semantic.model import SemanticModel
from frame.serve.engine import Engine
from frame.spec.schema import DashboardSpec, FilterClause, Param, QuerySpec

RELATIVE = re.compile(r"^@([a-z0-9_]+)\s*([+-])\s*(\d+)\s*([dwm])$", re.IGNORECASE)
LATEST = {"@latest", "@latest_close", "@max_date"}

_UNIT_DAYS = {"d": 1, "w": 7, "m": 30}


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    raise ValueError(f"cannot read {value!r} as a date")


# The watermark is shared process-wide and short-lived. Without this, every
# block request issues its own MAX(date) before the result cache is even
# consulted — a warehouse round-trip per request, which caps concurrency no
# matter how well the cache performs. Measured: 11.5 round-trips per dashboard
# load before, 0.06 after.
_WATERMARKS: dict[tuple[str, str], tuple[date, float]] = {}
_WATERMARK_LOCK = threading.Lock()


def latest_date(model: SemanticModel, engine: Engine, *, ttl: float | None = None) -> date:
    """The most recent date present in the model's first time-bearing source."""
    ttl = config.WATERMARK_TTL_SECONDS if ttl is None else ttl
    key = (model.name, engine.name)
    now = time.monotonic()

    cached = _WATERMARKS.get(key)
    if cached is not None and cached[1] > now:
        return cached[0]

    dialect = get_dialect(engine.dialect)
    resolved = date.today()
    for source in model.sources.values():
        if not source.time_column:
            continue
        sql = (
            # `column`, not `quote`: this is a physical column, and Snowflake
            # folds unquoted identifiers to upper case.
            f"SELECT MAX({dialect.column(source.time_column)}) "
            f"FROM {dialect.relation(source)}"
        )
        value = engine.scalar(sql)
        if value is not None:
            resolved = _as_date(value)
            break

    with _WATERMARK_LOCK:
        _WATERMARKS[key] = (resolved, now + ttl)
    return resolved


def reset_watermarks() -> None:
    with _WATERMARK_LOCK:
        _WATERMARKS.clear()


def resolve_value(
    raw: Any,
    param: Param,
    resolved: dict[str, Any],
    model: SemanticModel,
    engine: Engine,
) -> Any:
    if raw is None or not isinstance(raw, str):
        return raw

    token = raw.strip()

    if token.lower() in LATEST:
        return latest_date(model, engine)

    if token.lower() == "@today":
        return date.today()

    match = RELATIVE.match(token)
    if match:
        ref, sign, amount, unit = match.groups()
        if ref not in resolved:
            raise ValueError(
                f"param {param.name!r} refers to ${ref}, which is not declared before it"
            )
        base = _as_date(resolved[ref])
        days = int(amount) * _UNIT_DAYS[unit.lower()]
        return base - timedelta(days=days) if sign == "-" else base + timedelta(days=days)

    if param.type == "date":
        return _as_date(token)

    return token


def resolve_params(
    spec: DashboardSpec,
    model: SemanticModel,
    engine: Engine,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve in declaration order so later params may reference earlier ones."""
    overrides = overrides or {}
    resolved: dict[str, Any] = {}
    for param in spec.params:
        raw = overrides.get(param.name, param.default)
        resolved[param.name] = resolve_value(raw, param, resolved, model, engine)
    return resolved


def param_filters(spec: DashboardSpec, values: dict[str, Any]) -> list[FilterClause]:
    """Dimension params become filter clauses on every block's query."""
    out: list[FilterClause] = []
    for param in spec.params:
        if param.type != "dimension" or not param.of:
            continue
        value = values.get(param.name)
        if value in (None, "", []):
            continue
        if param.multi:
            values_list = value if isinstance(value, list) else [value]
            out.append(FilterClause(field=param.of, op="in", value=values_list))
        else:
            out.append(FilterClause(field=param.of, op="eq", value=value))
    return out


def bind_query(query: QuerySpec, values: dict[str, Any]) -> tuple[QuerySpec, date | None]:
    """Substitute $param references inside a block's query."""
    bound = query.model_copy(deep=True)
    compare_to: date | None = None

    if bound.compare:
        token = bound.compare
        if token.startswith("$"):
            name = token[1:]
            if name not in values:
                raise ValueError(f"query compares to unknown param ${name}")
            compare_to = _as_date(values[name])
        else:
            compare_to = _as_date(token)

    for clause in bound.filters:
        if isinstance(clause.value, str) and clause.value.startswith("$"):
            clause.value = values.get(clause.value[1:])

    return bound, compare_to
