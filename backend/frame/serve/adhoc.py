"""Running SQL a person wrote, for a scratchpad block.

This is the one path in the platform where SQL does not come from the compiler.
It exists because personal exploration is a real need and a governed metric is
not always the right answer to it. Everything here is about containing what
that costs.

## The only real boundary is the database role

Nothing in this module can make arbitrary SQL safe by inspecting it. String
checks catch typos and honest mistakes; they do not stop someone determined,
and pretending otherwise would be worse than not having them.

What actually contains a user's SQL is **the role it executes as**. If the
service connects to Snowflake with one shared role and runs user SQL under it,
every user can read everything the service can read, and row access policies
are bypassed entirely. If it executes as *that user's* role, then Snowflake's
own grants and row access policies are the boundary — the same boundary that
applies when they open a worksheet — and this module only has to bound cost.

`Identity.warehouse_role` is that hook. Running without it is only acceptable
when every viewer genuinely shares one data-access scope.

## What is contained here

* one statement only, and it must read
* a hard row cap, applied by wrapping the query rather than trusting it
* a statement timeout and a query tag, from the engine
* results are never shared between users: the cache key includes the subject,
  not just the policy fingerprint
"""

from __future__ import annotations

import re
from typing import Any

from frame.compile.guard import GuardError
from frame.identity import Identity
from frame.serve.engine import Engine, ResultSet

# Cheap, honest checks. Defence in depth, not the boundary — see the module
# docstring. A statement that gets past these is still bounded by the role.
_LEADING_OK = re.compile(r"^\s*(?:WITH|SELECT)\b", re.IGNORECASE)
_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|TRUNCATE|DROP|CREATE|ALTER|GRANT|REVOKE"
    r"|COPY|PUT|GET|CALL|EXECUTE|BEGIN|COMMIT|ROLLBACK|USE\s+ROLE|USE\s+WAREHOUSE)\b",
    re.IGNORECASE,
)
_COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)

MAX_SQL_LENGTH = 20_000


def strip_comments(sql: str) -> str:
    return _COMMENT.sub(" ", sql)


def check(sql: str) -> str:
    """Refuse what is obviously not a single read. Returns the cleaned SQL."""
    if not sql or not sql.strip():
        raise GuardError("empty_sql", "the query is empty")
    if len(sql) > MAX_SQL_LENGTH:
        raise GuardError(
            "sql_too_long",
            f"query is {len(sql):,} characters; the limit is {MAX_SQL_LENGTH:,}",
            length=len(sql),
            limit=MAX_SQL_LENGTH,
        )

    body = strip_comments(sql).strip().rstrip(";").strip()

    if ";" in body:
        raise GuardError(
            "multiple_statements",
            "only one statement can be run. Remove the ';' and everything after it.",
        )
    if not _LEADING_OK.match(body):
        raise GuardError(
            "not_a_query",
            "a block can only run a query. Start with SELECT or WITH.",
        )
    found = _FORBIDDEN.search(body)
    if found:
        raise GuardError(
            "write_statement_refused",
            f"{found.group(1).upper()} is not allowed here. A block reads; it does not write.",
            keyword=found.group(1).upper(),
        )
    return body


def wrap(sql: str, row_cap: int) -> str:
    """Bound the result by wrapping rather than trusting the query's own LIMIT.

    A user's LIMIT can be absent, wrong, or inside a subquery. Wrapping is the
    only version that always holds.
    """
    return f"SELECT * FROM (\n{sql}\n) AS frame_adhoc LIMIT {int(row_cap)}"


def _role(value: Any) -> str:
    """Infer a column's role from a value, so the existing marks can render an
    arbitrary result set without knowing anything about it."""
    if isinstance(value, bool):
        return "dimension"
    if isinstance(value, (int, float)):
        return "metric"
    return "dimension"


def run(
    engine: Engine,
    sql: str,
    identity: Identity,
    *,
    row_cap: int,
    query_tag: str = "frame:adhoc",
) -> ResultSet:
    """Execute a scratchpad query and shape it like any other block result."""
    body = check(sql)
    statement = wrap(body, row_cap)

    rows, names = engine.run_as(statement, identity, query_tag=query_tag)

    # Infer a role per column from the first non-null value in it, then add the
    # two synthetic columns every mark expects. A scratchpad result then renders
    # in a bar, a line or a table with no special-casing anywhere.
    roles: list[str] = []
    for index, name in enumerate(names):
        role = "dimension"
        for row in rows:
            if row[index] is not None:
                role = _role(row[index])
                break
        roles.append(role)

    columns: list[dict[str, Any]] = [
        {"name": "__period", "role": "period", "label": "Period", "format": {},
         "direction": "neutral"},
        {"name": "__rank", "role": "rank", "label": "Rank", "format": {},
         "direction": "neutral"},
    ]
    for name, role in zip(names, roles):
        columns.append(
            {
                "name": name,
                "role": role,
                "label": name.replace("_", " ").strip().title(),
                "format": {} if role == "dimension" else {"style": "decimal", "precision": 2},
                "direction": "neutral",
            }
        )

    shaped = [["current", i + 1, *row] for i, row in enumerate(rows)]
    return ResultSet(columns=columns, rows=shaped, elapsed_ms=0.0)
