"""Concurrent block queries must not read each other's result sets.

A dashboard fires one query per block at once, and FastAPI runs sync endpoints
in a threadpool. When those share a single DuckDB connection, each statement
overwrites the connection's pending result and blocks silently render another
block's numbers — plausible-looking ones, which is what makes it dangerous.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date

from frame.compile import CompileRequest, compile_query, get_dialect
from frame.identity import ANALYST
from frame.semantic import get_model
from frame.serve.engine import DuckDBEngine
from frame.spec.schema import QuerySpec

AS_OF = date(2026, 9, 8)


def _plan(model, metrics, by):
    return compile_query(
        CompileRequest(
            model=model,
            query=QuerySpec(metrics=metrics, by=by),
            as_of=AS_OF,
            identity=ANALYST,
            dialect=get_dialect("duckdb"),
        )
    )


def test_concurrent_queries_keep_their_own_columns():
    model = get_model("finance_ops")
    engine = DuckDBEngine()

    plans = [
        _plan(model, ["exception.count"], ["exception.team"]),
        _plan(model, ["exception.value_usd"], ["exception.region"]),
        _plan(model, ["exception.aging_days"], ["exception.reason_code"]),
        _plan(model, ["exception.count"], []),
    ]

    def run(plan):
        return plan, engine.execute(plan)

    with ThreadPoolExecutor(max_workers=8) as pool:
        # Several rounds: a single pass can get lucky on timing.
        results = list(pool.map(run, plans * 6))

    for plan, result in results:
        expected = [c.name for c in plan.columns]
        actual = [c["name"] for c in result.columns]
        assert actual == expected, (
            f"result carried another query's columns: {actual} != {expected}"
        )
        assert result.row_count > 0


def test_scalar_is_isolated_from_concurrent_execute():
    """`latest_date` runs a scalar while blocks are mid-flight."""
    model = get_model("finance_ops")
    engine = DuckDBEngine()
    plan = _plan(model, ["exception.count"], ["exception.reason_code"])

    def scalar(_: int):
        return engine.scalar("SELECT MAX(as_of_date) FROM fct_exception")

    def query(_: int):
        return engine.execute(plan).columns[0]["name"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        dates = list(pool.map(scalar, range(12)))
        names = list(pool.map(query, range(12)))

    assert all(d == "2026-09-08" for d in dates), dates
    assert all(n == "__period" for n in names), names
