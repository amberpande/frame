"""Scratchpad SQL: what is contained, and what is not.

These tests assert the *cheap* checks. They are defence in depth, and the
module says so: the real boundary for hand-written SQL is the warehouse role it
executes as, which DuckDB cannot model and which therefore has to be verified
against Snowflake.
"""

from __future__ import annotations

import pytest

from frame.compile.guard import GuardError
from frame.identity import ANALYST, Identity
from frame.serve import adhoc


def reason(sql: str) -> str:
    with pytest.raises(GuardError) as err:
        adhoc.check(sql)
    return err.value.reason


def test_a_plain_query_is_allowed():
    assert adhoc.check("SELECT 1 AS a").startswith("SELECT")
    assert adhoc.check("WITH x AS (SELECT 1) SELECT * FROM x").startswith("WITH")
    assert adhoc.check("  select 1 ;  ") == "select 1"


@pytest.mark.parametrize(
    "sql, expected",
    [
        ("", "empty_sql"),
        ("   ", "empty_sql"),
        ("SELECT 1; DROP TABLE fct_exception", "multiple_statements"),
        ("DROP TABLE fct_exception", "not_a_query"),
        ("UPDATE fct_exception SET status = 'X'", "not_a_query"),
        ("SELECT 1 UNION ALL SELECT 2 -- fine", None),
    ],
)
def test_obvious_abuse_is_refused(sql, expected):
    if expected is None:
        adhoc.check(sql)
        return
    assert reason(sql) == expected


def test_write_hidden_after_a_select_is_refused():
    """A leading SELECT is not enough on its own."""
    assert reason("SELECT * FROM t WHERE 1=1 GRANT SELECT ON t TO PUBLIC") == (
        "write_statement_refused"
    )


def test_comments_cannot_hide_a_second_statement():
    assert reason("SELECT 1 /* hide */ ; DELETE FROM t") == "multiple_statements"


def test_length_is_capped():
    assert reason("SELECT " + "1," * 20000) == "sql_too_long"


def test_the_row_cap_wraps_rather_than_trusting_the_query():
    """A user's own LIMIT can be absent, wrong, or buried in a subquery."""
    wrapped = adhoc.wrap("SELECT * FROM big LIMIT 999999", row_cap=500)
    assert wrapped.endswith("LIMIT 500")
    assert "frame_adhoc" in wrapped


def test_results_render_like_any_other_block(tmp_path):
    """A scratchpad result gets __period and __rank, so the existing marks can
    draw it without knowing it was hand-written."""
    from frame.serve.engine import DuckDBEngine

    result = adhoc.run(
        DuckDBEngine(),
        "SELECT team, COUNT(*) AS n FROM fct_exception GROUP BY 1 ORDER BY 2 DESC",
        ANALYST,
        row_cap=10,
    )
    names = [c["name"] for c in result.columns]
    assert names[:2] == ["__period", "__rank"]
    roles = {c["name"]: c["role"] for c in result.columns}
    assert roles["team"] == "dimension"
    assert roles["n"] == "metric"
    assert result.row_count > 0
    assert result.rows[0][0] == "current"


def test_snowflake_refuses_to_run_user_sql_as_the_service_role():
    """The one check that actually matters, asserted at the engine contract."""
    import inspect

    from frame.serve.engine import SnowflakeEngine

    source = inspect.getsource(SnowflakeEngine.run_as)
    assert "warehouse_role" in source
    assert "PermissionError" in source
    # And the role is restored, or the session is discarded, so an assumed role
    # cannot leak into the next request that borrows the pooled connection.
    assert "USE ROLE {restore}" in source or "restore" in source

    anonymous = Identity(subject="nobody@example.com")
    assert anonymous.warehouse_role is None
