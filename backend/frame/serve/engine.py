from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from frame import config
from frame.compile.plan import QueryPlan


@dataclass
class ResultSet:
    """Column-oriented on purpose.

    JSON today; the same shape drops straight onto an Arrow record batch when
    the wire format moves, without the client changing.
    """

    columns: list[dict[str, Any]]
    rows: list[list[Any]]
    elapsed_ms: float = 0.0

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def as_records(self) -> list[dict[str, Any]]:
        names = [c["name"] for c in self.columns]
        return [dict(zip(names, row)) for row in self.rows]


class Engine(ABC):
    name: str
    dialect: str

    # Warehouse round-trips since start, split by kind. Exposed on /health:
    # at scale this is the number that decides whether a deployment is
    # affordable, and it should not take a profiler to see it.
    def __init__(self) -> None:
        self.executes = 0
        self.scalars = 0

    def stats(self) -> dict[str, int]:
        return {"executes": self.executes, "scalars": self.scalars}

    @abstractmethod
    def execute(self, plan: QueryPlan) -> ResultSet: ...

    @abstractmethod
    def scalar(self, sql: str, params: dict[str, Any] | None = None) -> Any: ...

    @abstractmethod
    def fetch_all(self, sql: str, params: dict[str, Any] | None = None) -> list[tuple]: ...

    @abstractmethod
    def run_as(self, sql: str, identity: Any, *, query_tag: str) -> tuple[list[list], list[str]]:
        """Execute hand-written SQL as a specific person.

        Separate from `execute` on purpose: this path takes SQL the platform did
        not write, so it must run under that person's own warehouse role. That
        role, not any check in Python, is what bounds what they can read.
        """


def _serialize(value: Any) -> Any:
    import datetime as _dt
    import decimal as _decimal

    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.isoformat()
    if isinstance(value, _decimal.Decimal):
        return float(value)
    return value


class DuckDBEngine(Engine):
    """Local development, and the server-side cube tier in Phase 1."""

    name = "duckdb"
    dialect = "duckdb"

    def __init__(self, path: str | None = None) -> None:
        import duckdb

        super().__init__()

        self._path = str(path or config.DUCKDB_PATH)
        if not Path(self._path).exists():
            raise FileNotFoundError(
                f"no local fixture at {self._path} - run `python seed/build_seed.py` first"
            )
        # Read-only, because the query service has no business writing to the
        # warehouse. It also lets several readers share the file, so tests and
        # a running server do not fight over a write lock.
        self._con = duckdb.connect(self._path, read_only=True)

    def _cursor(self):
        """A fresh cursor per statement.

        A DuckDB connection carries the result of the last statement run on it.
        FastAPI runs sync endpoints in a threadpool, so a dashboard's blocks
        query concurrently on the same connection and read each other's rows —
        silently, and with plausible-looking numbers. `.cursor()` returns an
        independent connection over the same database, which is the documented
        way to use DuckDB from several threads.
        """
        return self._con.cursor()

    def execute(self, plan: QueryPlan) -> ResultSet:
        started = time.perf_counter()
        self.executes += 1
        cur = self._cursor()
        cur.execute(plan.sql, plan.params)
        raw = cur.fetchall()
        description = cur.description or []
        elapsed = (time.perf_counter() - started) * 1000
        columns = [{"name": c.name, "role": c.role, "label": c.label,
                    "format": c.format, "direction": c.direction} for c in plan.columns]
        if len(description) != len(columns):
            columns = [{"name": desc[0], "role": "metric", "label": desc[0],
                        "format": {}, "direction": "neutral"} for desc in description]
        rows = [[_serialize(v) for v in row] for row in raw]
        return ResultSet(columns=columns, rows=rows, elapsed_ms=elapsed)

    def scalar(self, sql: str, params: dict[str, Any] | None = None) -> Any:
        self.scalars += 1
        cur = self._cursor()
        cur.execute(sql, params or {})
        row = cur.fetchone()
        return _serialize(row[0]) if row else None

    def fetch_all(self, sql: str, params: dict[str, Any] | None = None) -> list[tuple]:
        cur = self._cursor()
        cur.execute(sql, params or {})
        return [tuple(_serialize(v) for v in row) for row in cur.fetchall()]

    def run_as(self, sql: str, identity: Any, *, query_tag: str) -> tuple[list[list], list[str]]:
        # DuckDB has no roles, so local development cannot reproduce the real
        # boundary. That is a property of the fixture, not of the design: role
        # isolation has to be tested against Snowflake.
        self.executes += 1
        cur = self._cursor()
        cur.execute(sql)
        names = [d[0] for d in (cur.description or [])]
        rows = [[_serialize(v) for v in row] for row in cur.fetchall()]
        return rows, names


class SnowflakeEngine(Engine):
    """The paid path.

    Connections are kept per worker thread rather than opened per query.
    Establishing a Snowflake session costs a few hundred milliseconds — on a
    dashboard firing a dozen block queries that is the entire latency budget
    spent on handshakes. Thread-local also keeps each request's cursor
    isolated, the same requirement that bit the DuckDB engine.
    """

    name = "snowflake"
    dialect = "snowflake"

    def __init__(self) -> None:
        import os
        import threading

        super().__init__()

        import snowflake.connector  # type: ignore[import-not-found]

        self._connect = snowflake.connector.connect
        self._local = threading.local()
        self._opts: dict[str, Any] = {
            "account": os.environ["SNOWFLAKE_ACCOUNT"],
            "user": os.environ["SNOWFLAKE_USER"],
            "warehouse": os.environ.get("SNOWFLAKE_WAREHOUSE", "FRAME_INTERACTIVE_XS"),
            "database": os.environ.get("SNOWFLAKE_DATABASE"),
            "schema": os.environ.get("SNOWFLAKE_SCHEMA"),
            "role": os.environ.get("SNOWFLAKE_ROLE"),
            "client_session_keep_alive": True,
        }
        if pwd := os.environ.get("SNOWFLAKE_PASSWORD"):
            self._opts["password"] = pwd
        if key := os.environ.get("SNOWFLAKE_PRIVATE_KEY_PATH"):
            self._opts["private_key_file"] = key
            if passphrase := os.environ.get("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE"):
                self._opts["private_key_file_pwd"] = passphrase
        if authenticator := os.environ.get("SNOWFLAKE_AUTHENTICATOR"):
            self._opts["authenticator"] = authenticator

    def _connection(self):
        con = getattr(self._local, "con", None)
        if con is not None and not con.is_closed():
            return con
        con = self._connect(**{k: v for k, v in self._opts.items() if v not in (None, "")})
        # A runaway interactive query must die on its own rather than hold a
        # warehouse open. Set once per session, not per statement.
        con.cursor().execute(
            "ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = "
            f"{config.STATEMENT_TIMEOUT_SECONDS}"
        )
        self._local.con = con
        return con

    def _route(self, cur, plan: QueryPlan) -> str:
        """Send heavy work to its own warehouse.

        An expensive block queued on the interactive cluster delays every cheap
        block behind it. Routing by the plan's cost class keeps the fast path
        fast; the switch is skipped when the session is already there, because
        USE WAREHOUSE is not free either.
        """
        heavy = config.SNOWFLAKE_WAREHOUSE_HEAVY
        target = self._opts.get("warehouse", "")
        if heavy and plan.cost.cost_class in ("moderate", "expensive"):
            target = heavy
        if target and getattr(self._local, "warehouse", None) != target:
            cur.execute(f"USE WAREHOUSE {target}")
            self._local.warehouse = target
        return target

    def execute(self, plan: QueryPlan) -> ResultSet:
        started = time.perf_counter()
        self.executes += 1
        cur = self._connection().cursor()
        try:
            self._route(cur, plan)
            # Cost attribution per dashboard, per plan — not per user. This is
            # what makes "which dashboard is burning credits" answerable.
            cur.execute("ALTER SESSION SET QUERY_TAG = %(tag)s", {"tag": plan.query_tag})
            cur.execute(plan.sql, plan.params)
            raw = cur.fetchall()
        finally:
            cur.close()
        elapsed = (time.perf_counter() - started) * 1000
        columns = [{"name": c.name, "role": c.role, "label": c.label,
                    "format": c.format, "direction": c.direction} for c in plan.columns]
        rows = [[_serialize(v) for v in row] for row in raw]
        return ResultSet(columns=columns, rows=rows, elapsed_ms=elapsed)

    def scalar(self, sql: str, params: dict[str, Any] | None = None) -> Any:
        self.scalars += 1
        cur = self._connection().cursor()
        try:
            cur.execute(sql, params or {})
            row = cur.fetchone()
        finally:
            cur.close()
        return _serialize(row[0]) if row else None

    def run_as(self, sql: str, identity: Any, *, query_tag: str) -> tuple[list[list], list[str]]:
        """Run under the caller's own role, not the service role.

        `USE ROLE` requires the service user to have been granted that role.
        Without one the query would run as the service account, so one person's
        ad-hoc SQL could read everything the service can. Refuse rather than do
        that silently.
        """
        role = getattr(identity, "warehouse_role", None)
        if not role:
            raise PermissionError(
                f"{getattr(identity, 'subject', 'this identity')} has no warehouse_role; "
                "refusing to run hand-written SQL as the shared service role"
            )
        if not re.fullmatch(r"[A-Za-z0-9_$]+", role):
            raise PermissionError(f"illegal warehouse role {role!r}")

        self.executes += 1
        con = self._connection()
        cur = con.cursor()
        try:
            cur.execute(f"USE ROLE {role}")
            cur.execute("ALTER SESSION SET QUERY_TAG = %(tag)s", {"tag": query_tag})
            cur.execute(sql)
            names = [d[0] for d in (cur.description or [])]
            rows = [[_serialize(v) for v in row] for row in cur.fetchall()]
        finally:
            cur.close()
            # Connections are pooled per thread, so the assumed role must not
            # leak into the next request that borrows this session.
            restore = self._opts.get("role")
            if restore:
                try:
                    con.cursor().execute(f"USE ROLE {restore}")
                except Exception:
                    self._local.con = None  # poisoned: force a fresh session
            self._local.warehouse = None
        return rows, names

    def fetch_all(self, sql: str, params: dict[str, Any] | None = None) -> list[tuple]:
        cur = self._connection().cursor()
        try:
            cur.execute(sql, params or {})
            raw = cur.fetchall()
        finally:
            cur.close()
        return [tuple(_serialize(v) for v in row) for row in raw]


_ENGINE: Engine | None = None


def get_engine() -> Engine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = SnowflakeEngine() if config.ENGINE == "snowflake" else DuckDBEngine()
    return _ENGINE


def reset_engine() -> None:
    global _ENGINE
    _ENGINE = None
