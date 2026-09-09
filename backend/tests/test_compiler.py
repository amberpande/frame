from __future__ import annotations

from datetime import date

import pytest

from frame.compile import CompileRequest, GuardError, compile_query, get_dialect
from frame.identity import ANALYST, EMEA_ANALYST, RESTRICTED
from frame.semantic import get_model
from frame.spec.schema import FilterClause, QuerySpec, SortSpec

AS_OF = date(2026, 9, 8)
COMPARE = date(2026, 9, 1)


@pytest.fixture(scope="module")
def model():
    return get_model("finance_ops")


def plan_for(model, query, identity=ANALYST, compare=COMPARE):
    return compile_query(
        CompileRequest(
            model=model,
            query=query,
            as_of=AS_OF,
            compare_to=compare,
            identity=identity,
            dialect=get_dialect("duckdb"),
        )
    )


def test_compare_emits_both_periods(model):
    plan = plan_for(
        model,
        QuerySpec(metrics=["exception.count"], by=["exception.reason_code"], limit=5),
    )
    assert "'current'" in plan.sql and "'compare'" in plan.sql
    assert "UNION ALL" in plan.sql


def test_limit_ranks_groups_not_rows(model):
    """Limiting rows would truncate one side of a comparison and misstate
    every variance on the page."""
    plan = plan_for(
        model,
        QuerySpec(
            metrics=["exception.count", "severity.signed_z"],
            by=["exception.reason_code"],
            limit=3,
            order=SortSpec(by="severity.signed_z", dir="desc", abs=True),
        ),
    )
    assert "ranked AS" in plan.sql
    assert "ROW_NUMBER() OVER" in plan.sql
    assert "ABS(" in plan.sql  # signed severity ranks on magnitude


def test_baseline_cte_only_when_needed(model):
    with_severity = plan_for(
        model, QuerySpec(metrics=["severity.signed_z"], by=["exception.team"])
    )
    assert "hist AS" in with_severity.sql and "base AS" in with_severity.sql

    without = plan_for(model, QuerySpec(metrics=["exception.count"], by=["exception.team"]))
    assert "hist AS" not in without.sql


def test_grain_violation_is_refused(model):
    """Slicing a metric by a dimension it was never grained on is the classic
    silently-wrong answer. sla.breach_rate comes from a summary grained to team
    only, so cutting it by reason code must be a rejection, not a number."""
    with pytest.raises(GuardError) as err:
        plan_for(
            model,
            QuerySpec(metrics=["sla.breach_rate"], by=["exception.reason_code"]),
        )
    assert err.value.reason == "grain_violation"
    assert err.value.to_dict()["allowed"] == ["sla.as_of_date", "sla.team"]


def test_mixing_sources_is_refused(model):
    """No declared join paths yet, so a query spanning two sources is refused
    rather than silently producing a cross join."""
    with pytest.raises(GuardError) as err:
        plan_for(model, QuerySpec(metrics=["exception.count", "sla.breached"]))
    assert err.value.reason == "multi_source_query"


def test_ratio_metric_compiles_over_its_own_source(model):
    plan = plan_for(model, QuerySpec(metrics=["sla.breach_rate"], by=["sla.team"]))
    assert "agg_team_sla" in plan.sql
    assert "NULLIF" in plan.sql


def test_unknown_metric_is_structured(model):
    with pytest.raises(GuardError) as err:
        plan_for(model, QuerySpec(metrics=["revenue.total"]))
    assert err.value.reason == "unknown_metric"
    assert "available" in err.value.to_dict()


def test_forbidden_metric_for_identity(model):
    with pytest.raises(GuardError) as err:
        plan_for(model, QuerySpec(metrics=["exception.value_usd"]), identity=RESTRICTED)
    assert err.value.reason == "metric_forbidden"


def test_policy_changes_the_cache_key(model):
    """The trap: cache keyed on the query, RLS applied per user. The policy
    fingerprint must be part of the key or rows leak between identities."""
    query = QuerySpec(metrics=["exception.count"], by=["exception.team"])
    a = plan_for(model, query, identity=ANALYST)
    b = plan_for(model, query, identity=EMEA_ANALYST)
    assert a.policy_fingerprint != b.policy_fingerprint
    assert a.hash != b.hash


def test_row_predicates_are_injected_not_carried(model):
    plan = plan_for(
        model,
        QuerySpec(metrics=["exception.count"], by=["exception.team"]),
        identity=EMEA_ANALYST,
    )
    assert "region IN ('EMEA')" in plan.sql


def test_filters_are_bound_not_interpolated(model):
    plan = plan_for(
        model,
        QuerySpec(
            metrics=["exception.count"],
            by=["exception.team"],
            filters=[FilterClause(field="exception.region", op="in", value=["AMER", "EMEA"])],
        ),
    )
    assert "AMER" not in plan.sql
    assert "AMER" in plan.params.values()


def test_limit_cap_is_enforced(model):
    with pytest.raises(GuardError) as err:
        compile_query(
            CompileRequest(
                model=model,
                query=QuerySpec(metrics=["exception.count"], limit=999_999),
                as_of=AS_OF,
                identity=ANALYST,
                dialect=get_dialect("duckdb"),
                row_cap=1000,
            )
        )
    assert err.value.reason == "limit_exceeds_cap"


def test_snowflake_dialect_targets_the_real_relation(model):
    plan = compile_query(
        CompileRequest(
            model=model,
            query=QuerySpec(metrics=["exception.count"], by=["exception.team"]),
            as_of=AS_OF,
            identity=ANALYST,
            dialect=get_dialect("snowflake"),
        )
    )
    assert "ANALYTICS.OPS.FCT_EXCEPTION" in plan.sql
    assert "%(p0)s" in plan.sql


def test_time_series_widens_to_a_window(model):
    """Grouping by a time dimension must scan a range, not the as-of date."""
    plan = plan_for(
        model,
        QuerySpec(
            metrics=["exception.count"],
            by=["exception.as_of_date"],
            window_days=30,
        ),
        compare=None,
    )
    assert "> $p0" in plan.sql and "<= $p1" in plan.sql
    assert plan.params["p0"] == date(2026, 8, 9)
    assert plan.params["p1"] == AS_OF


def test_series_refuses_a_comparison_period(model):
    """A line already shows change over time; a compare would double every point."""
    with pytest.raises(GuardError) as err:
        plan_for(
            model,
            QuerySpec(metrics=["exception.count"], by=["exception.as_of_date"]),
        )
    assert err.value.reason == "compare_with_time_series"


def test_series_refuses_a_baseline_metric(model):
    with pytest.raises(GuardError) as err:
        plan_for(
            model,
            QuerySpec(metrics=["severity.signed_z"], by=["exception.as_of_date"]),
            compare=None,
        )
    assert err.value.reason == "baseline_with_time_series"


def test_snowflake_uppercases_physical_columns_but_not_aliases(model):
    """Snowflake folds unquoted identifiers to upper case at creation time, so
    a lower-case quoted column never resolves. Output aliases must survive
    verbatim, because the client keys on them."""
    plan = compile_query(
        CompileRequest(
            model=model,
            query=QuerySpec(metrics=["exception.count"], by=["exception.vendor_tier"]),
            as_of=AS_OF,
            identity=ANALYST,
            dialect=get_dialect("snowflake"),
        )
    )
    assert '"VENDOR_TIER"' in plan.sql          # physical column, folded
    assert '"EXCEPTION_ID"' in plan.sql
    assert '"exception.count"' in plan.sql      # output alias, verbatim
    assert '"exception.vendor_tier"' in plan.sql
    assert '"vendor_tier" AS' not in plan.sql


def test_duckdb_leaves_physical_columns_alone(model):
    plan = plan_for(
        model,
        QuerySpec(metrics=["exception.count"], by=["exception.vendor_tier"]),
        compare=None,
    )
    assert '"vendor_tier"' in plan.sql
    assert '"VENDOR_TIER"' not in plan.sql


def test_large_unfiltered_scan_is_refused(model):
    """The likeliest expensive mistake against an unmodelled warehouse: a
    dashboard pointed at a huge table with nothing to prune on."""
    import copy

    big = copy.deepcopy(model)
    source = big.sources["fct_exception"]
    source.time_column = None          # a snapshot or dimension table
    source.row_estimate = 900_000_000

    with pytest.raises(GuardError) as err:
        compile_query(
            CompileRequest(
                model=big,
                query=QuerySpec(metrics=["exception.count"], by=["exception.team"]),
                as_of=AS_OF,
                identity=ANALYST,
                dialect=get_dialect("duckdb"),
                large_table_rows=50_000_000,
            )
        )
    assert err.value.reason == "large_unfiltered_scan"

    # A filter makes it prunable, so it is allowed.
    plan = compile_query(
        CompileRequest(
            model=big,
            query=QuerySpec(
                metrics=["exception.count"],
                by=["exception.team"],
                filters=[FilterClause(field="exception.region", op="eq", value="EMEA")],
            ),
            as_of=AS_OF,
            identity=ANALYST,
            dialect=get_dialect("duckdb"),
            large_table_rows=50_000_000,
        )
    )
    assert "as_of_date" not in plan.sql   # no time column, so no time predicate


def test_approx_distinct_is_opt_in(model):
    import copy

    approx_model = copy.deepcopy(model)
    approx_model.metric("exception.count").approx = True
    plan = compile_query(
        CompileRequest(
            model=approx_model,
            query=QuerySpec(metrics=["exception.count"], by=["exception.team"]),
            as_of=AS_OF,
            identity=ANALYST,
            dialect=get_dialect("snowflake"),
        )
    )
    assert "APPROX_COUNT_DISTINCT" in plan.sql
    assert "COUNT(DISTINCT" not in plan.sql
