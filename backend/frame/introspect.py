"""Generate a draft semantic model by introspecting the warehouse.

The semantic layer is not optional — it is what makes the guards, the cache key
and the agent safe. But hand-authoring it does not survive contact with five
thousand tables, and a platform you cannot use until the modelling is finished
is a platform nobody adopts.

So the model is *generated* and curated incrementally. Introspection reads
`INFORMATION_SCHEMA`, profiles the columns that matter, and writes YAML with
`curated: false` on everything. That YAML is a real semantic model the moment
it lands: the compiler, the guards and the cache all work against it unchanged.
Curation is then editing a file — renaming, deleting the nonsense, adding an
owner and a test — and the share of curated definitions is a number you can
report on rather than a project you have to finish first.

    python -m frame.introspect --list --schema OPS
    python -m frame.introspect --schema OPS --tables FCT_EXCEPTION,AGG_TEAM_SLA \\
        --name ops --out models/ops.yml
    python -m frame.introspect --schema OPS --rank-by-usage --top 25

Nothing here runs against the serving path, and nothing it writes is trusted:
the generated file goes through exactly the same validation as a hand-written
one.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from typing import Any

import yaml

from frame import config
from frame.compile.dialects import get_dialect
from frame.serve.engine import Engine, get_engine

# ---------------------------------------------------------------- inference

TIME_TYPES = {"DATE", "TIMESTAMP", "TIMESTAMP_NTZ", "TIMESTAMP_LTZ", "TIMESTAMP_TZ",
              "DATETIME", "TIMESTAMP WITH TIME ZONE", "TIMESTAMP WITHOUT TIME ZONE"}
NUMERIC_TYPES = {"NUMBER", "DECIMAL", "NUMERIC", "INT", "INTEGER", "BIGINT", "SMALLINT",
                 "TINYINT", "FLOAT", "FLOAT8", "DOUBLE", "DOUBLE PRECISION", "REAL",
                 "HUGEINT", "UBIGINT"}
TEXT_TYPES = {"VARCHAR", "TEXT", "STRING", "CHAR", "CHARACTER"}
BOOL_TYPES = {"BOOLEAN", "BOOL"}
SKIP_TYPES = {"VARIANT", "OBJECT", "ARRAY", "GEOGRAPHY", "GEOMETRY", "BINARY", "BLOB"}

# A column named like a key is something you count, not something you sum.
ID_LIKE = re.compile(r"(^|_)(id|key|no|num|number|code|uuid|guid)$", re.I)
# Ratios must be averaged; summing them is meaningless.
RATE_LIKE = re.compile(r"(rate|ratio|pct|percent|score|avg|average|mean|index)", re.I)
MONEY_LIKE = re.compile(r"(amount|amt|value|price|cost|revenue|spend|usd|eur|gbp|total)", re.I)
# Durations are the ambiguous case: summing an age is meaningless, but summing
# effort is not. Averaging is right more often, and the note says so out loud
# rather than leaving a plausible wrong number on a page.
DURATION_LIKE = re.compile(r"(_days|_hours|_minutes|_seconds|_age$|^age_|duration|latency|elapsed|tenure)", re.I)
# Preferred as-of columns, best first.
TIME_PREFERENCE = ["as_of_date", "as_of", "snapshot_date", "business_date", "report_date",
                   "event_date", "activity_date", "transaction_date", "order_date",
                   "created_date", "created_at", "updated_at", "loaded_at"]
TABLE_PREFIXES = ("fct_", "fact_", "dim_", "agg_", "stg_", "int_", "rpt_", "vw_", "v_")


def _base_type(raw: str) -> str:
    return re.split(r"[(<]", (raw or "").upper().strip(), maxsplit=1)[0].strip()


def _entity_name(table: str) -> str:
    """FCT_EXCEPTION -> exception. The metric namespace for this table."""
    name = table.lower()
    for prefix in TABLE_PREFIXES:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return re.sub(r"[^a-z0-9_]", "_", name).strip("_") or "table"


def _label(column: str) -> str:
    words = re.sub(r"[_\s]+", " ", column.strip()).strip()
    return words[:1].upper() + words[1:] if words else column


@dataclass
class Column:
    name: str
    data_type: str
    nullable: bool = True
    cardinality: int | None = None

    @property
    def base(self) -> str:
        return _base_type(self.data_type)

    @property
    def is_time(self) -> bool:
        return self.base in TIME_TYPES

    @property
    def is_numeric(self) -> bool:
        return self.base in NUMERIC_TYPES

    @property
    def is_text(self) -> bool:
        return self.base in TEXT_TYPES

    @property
    def is_bool(self) -> bool:
        return self.base in BOOL_TYPES

    @property
    def is_skipped(self) -> bool:
        return self.base in SKIP_TYPES or not self.base


@dataclass
class TableInfo:
    database: str | None
    schema: str
    table: str
    columns: list[Column] = field(default_factory=list)
    row_count: int | None = None

    @property
    def relation(self) -> str:
        parts = [p for p in (self.database, self.schema, self.table) if p]
        return ".".join(parts)

    @property
    def entity(self) -> str:
        return _entity_name(self.table)


# --------------------------------------------------------------- warehouse

def _information_schema(database: str | None) -> str:
    return f"{database}.INFORMATION_SCHEMA" if database else "information_schema"


def list_tables(
    engine: Engine,
    schema: str | None = None,
    database: str | None = None,
    pattern: str | None = None,
) -> list[tuple[str, str]]:
    """(schema, table) pairs visible to the connected role."""
    where = ["table_type IN ('BASE TABLE', 'VIEW')"]
    if schema:
        where.append(f"UPPER(table_schema) = UPPER('{_safe(schema)}')")
    if pattern:
        where.append(f"UPPER(table_name) LIKE UPPER('{_safe(pattern)}')")
    sql = (
        f"SELECT table_schema, table_name FROM {_information_schema(database)}.TABLES "
        f"WHERE {' AND '.join(where)} ORDER BY 1, 2"
    )
    return [(str(r[0]), str(r[1])) for r in engine.fetch_all(sql)]


def describe(
    engine: Engine,
    table: str,
    schema: str | None = None,
    database: str | None = None,
) -> TableInfo:
    sql = (
        "SELECT column_name, data_type, is_nullable "
        f"FROM {_information_schema(database)}.COLUMNS "
        f"WHERE UPPER(table_name) = UPPER('{_safe(table)}')"
    )
    if schema:
        sql += f" AND UPPER(table_schema) = UPPER('{_safe(schema)}')"
    sql += " ORDER BY ordinal_position"

    columns = [
        Column(name=str(r[0]), data_type=str(r[1]), nullable=str(r[2]).upper() != "NO")
        for r in engine.fetch_all(sql)
    ]
    if not columns:
        raise LookupError(f"no columns found for {schema or ''}.{table} — check name and grants")
    return TableInfo(database=database, schema=schema or "", table=table, columns=columns)


def profile(engine: Engine, info: TableInfo, sample_days: int | None = 90) -> None:
    """One query per table: row count plus approximate distinct per column.

    Distinct counts are what decide whether a text column is a dimension you
    can group by or a high-cardinality field that would produce a wall. HLL
    keeps this cheap enough to run across a whole schema.
    """
    dialect = get_dialect(engine.dialect)
    candidates = [c for c in info.columns if not c.is_skipped]
    if not candidates:
        return

    time_col = pick_time_column(info)
    where = ""
    if time_col and sample_days:
        # Profile a recent window rather than all history: a clustered fact
        # table prunes to a few partitions instead of a full scan.
        where = (
            f" WHERE {dialect.column(time_col.name)} >= "
            f"(SELECT MAX({dialect.column(time_col.name)}) FROM {info.relation}) "
            f"- {sample_days}"
        )

    projections = ", ".join(
        f"APPROX_COUNT_DISTINCT({dialect.column(c.name)}) AS c{i}"
        for i, c in enumerate(candidates)
    )
    sql = f"SELECT COUNT(*) AS n, {projections} FROM {info.relation}{where}"

    try:
        row = engine.fetch_all(sql)[0]
    except Exception as exc:  # profiling is best-effort; inference still works
        print(f"  ! could not profile {info.relation}: {str(exc).splitlines()[0]}", file=sys.stderr)
        return

    info.row_count = int(row[0]) if row[0] is not None else None
    for i, column in enumerate(candidates):
        value = row[i + 1]
        column.cardinality = int(value) if value is not None else None


def pick_time_column(info: TableInfo) -> Column | None:
    times = [c for c in info.columns if c.is_time]
    if not times:
        return None
    for preferred in TIME_PREFERENCE:
        for column in times:
            if column.name.lower() == preferred:
                return column
    return times[0]


def _safe(value: str) -> str:
    """Identifiers and patterns are interpolated into INFORMATION_SCHEMA
    predicates, so anything but word characters and wildcards is rejected."""
    if not re.fullmatch(r"[A-Za-z0-9_%.\-]+", value or ""):
        raise ValueError(f"unsafe identifier {value!r}")
    return value


# ---------------------------------------------------------------- generate

@dataclass
class Options:
    max_dimension_cardinality: int = 500
    max_grain_cardinality: int = 200
    approx_threshold: int = 100_000
    include_id_measures: bool = True


def build_model(
    name: str,
    tables: list[TableInfo],
    options: Options | None = None,
) -> dict[str, Any]:
    """Turn profiled tables into a semantic model document.

    Everything produced is `curated: false`. It is a draft, and the point of
    saying so in the file is that the platform can count what remains.
    """
    opt = options or Options()
    sources: dict[str, Any] = {}
    dimensions: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []
    notes: list[str] = []

    for info in tables:
        entity = info.entity
        source_key = info.table.lower()
        time_column = pick_time_column(info)

        sources[source_key] = {
            "relation": info.relation,
            "curated": False,
            **({"time_column": time_column.name} if time_column else {}),
            **({"row_estimate": info.row_count} if info.row_count is not None else {}),
        }

        grain: list[str] = []

        for column in info.columns:
            if column.is_skipped:
                notes.append(f"{info.table}.{column.name}: {column.base} not modelled")
                continue

            dim_name = f"{entity}.{column.name.lower()}"

            # --- time -------------------------------------------------------
            if column.is_time:
                dimensions.append({
                    "name": dim_name, "label": _label(column.name),
                    "source": source_key, "column": column.name,
                    "kind": "time", "curated": False,
                })
                if time_column and column.name == time_column.name:
                    grain.insert(0, dim_name)
                continue

            # --- booleans and low-cardinality text are dimensions ------------
            if column.is_bool or (
                column.is_text
                and (column.cardinality is None or column.cardinality <= opt.max_dimension_cardinality)
            ):
                dimensions.append({
                    "name": dim_name, "label": _label(column.name),
                    "source": source_key, "column": column.name,
                    "curated": False,
                    **({"cardinality": column.cardinality} if column.cardinality is not None else {}),
                })
                if column.cardinality is not None and column.cardinality <= opt.max_grain_cardinality:
                    grain.append(dim_name)
                elif column.cardinality is None:
                    grain.append(dim_name)
                continue

            # --- high-cardinality text: countable, not groupable --------------
            if column.is_text:
                if opt.include_id_measures:
                    metrics.append(_count_metric(entity, source_key, column, opt))
                notes.append(
                    f"{info.table}.{column.name}: {column.cardinality:,} distinct — "
                    "too many to group by, exposed as a distinct count"
                )
                continue

            # --- numerics ----------------------------------------------------
            if column.is_numeric:
                if ID_LIKE.search(column.name):
                    if opt.include_id_measures:
                        metrics.append(_count_metric(entity, source_key, column, opt))
                    continue
                is_rate = bool(RATE_LIKE.search(column.name))
                is_duration = bool(DURATION_LIKE.search(column.name))
                agg = "avg" if (is_rate or is_duration) else "sum"

                fmt: dict[str, Any] = {"style": "decimal", "precision": 2}
                if MONEY_LIKE.search(column.name):
                    fmt = {"style": "currency", "currency": "USD", "compact": True}

                metric: dict[str, Any] = {
                    "name": f"{entity}.{column.name.lower()}",
                    "label": _label(column.name),
                    "kind": "measure", "source": source_key,
                    "agg": agg, "column": column.name,
                    "format": fmt, "curated": False,
                    "synonyms": [column.name.lower().replace("_", " ")],
                }
                if is_duration:
                    metric["note"] = (
                        "Aggregate inferred as AVG because the name looks like a duration. "
                        "Summing durations is meaningful for effort and meaningless for age "
                        "- confirm before setting curated: true."
                    )
                    notes.append(
                        f"{info.table}.{column.name}: ambiguous aggregate, defaulted to AVG"
                    )
                metrics.append(metric)

        # Every table gets a row count: the one measure that is always correct.
        metrics.append({
            "name": f"{entity}.row_count", "label": "Rows",
            "kind": "measure", "source": source_key, "agg": "count",
            "format": {"style": "integer"}, "curated": False,
            "synonyms": ["rows", "row count", "records", "count"],
        })

        for metric in metrics:
            if metric.get("source") == source_key and "grain" not in metric:
                metric["grain"] = list(grain)

    document: dict[str, Any] = {
        "name": name,
        "version": 1,
        "label": name.replace("_", " ").title(),
        "description": (
            "Generated by frame.introspect. Every definition is curated: false — "
            "a draft that works today and is meant to be edited down."
        ),
        "sources": sources,
        "dimensions": dimensions,
        "metrics": metrics,
    }
    if notes:
        document["x-introspection-notes"] = notes
    return document


def _count_metric(entity: str, source_key: str, column: Column, opt: Options) -> dict[str, Any]:
    approx = column.cardinality is not None and column.cardinality >= opt.approx_threshold
    metric: dict[str, Any] = {
        "name": f"{entity}.distinct_{column.name.lower()}",
        "label": f"Distinct {_label(column.name).lower()}",
        "kind": "measure", "source": source_key,
        "agg": "count_distinct", "column": column.name,
        "format": {"style": "integer"}, "curated": False,
        "synonyms": [f"distinct {column.name.lower().replace('_', ' ')}"],
    }
    if approx:
        # HyperLogLog: within a fraction of a percent, and the difference
        # between a cheap query and an expensive one at this cardinality.
        metric["approx"] = True
        metric["cost_class"] = "moderate"
        metric["note"] = (
            f"Approximate (HyperLogLog): ~{column.cardinality:,} distinct values make "
            "an exact count expensive. Set approx: false if you need it exact."
        )
    return metric


# -------------------------------------------------------- usage ranking

USAGE_SQL = """
SELECT
    base.value:objectName::string        AS table_name,
    COUNT(*)                             AS query_count,
    COUNT(DISTINCT q.user_name)          AS distinct_users,
    MAX(q.start_time)                    AS last_queried
FROM SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY a
JOIN SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY  q ON q.query_id = a.query_id,
     LATERAL FLATTEN(input => a.base_objects_accessed) base
WHERE q.start_time >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
  AND base.value:objectDomain::string = 'Table'
GROUP BY 1
ORDER BY query_count DESC
LIMIT {limit}
"""


def rank_by_usage(engine: Engine, days: int = 90, limit: int = 50) -> list[tuple]:
    """Which tables are actually queried — the only sane way to choose from
    five thousand. Snowflake only; ACCOUNT_USAGE latency is up to ~3 hours."""
    if engine.dialect != "snowflake":
        raise RuntimeError("usage ranking reads SNOWFLAKE.ACCOUNT_USAGE and needs Snowflake")
    return engine.fetch_all(USAGE_SQL.format(days=days, limit=limit))


# ------------------------------------------------------------------- CLI

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--schema", help="schema to read from")
    parser.add_argument("--database", help="database (Snowflake); omit for DuckDB")
    parser.add_argument("--tables", help="comma-separated table names")
    parser.add_argument("--like", help="table name pattern, e.g. FCT_%%")
    parser.add_argument("--name", default="draft", help="semantic model name")
    parser.add_argument("--out", help="write YAML here; default is stdout")
    parser.add_argument("--list", action="store_true", help="list visible tables and exit")
    parser.add_argument("--rank-by-usage", action="store_true",
                        help="rank tables by real query volume (Snowflake)")
    parser.add_argument("--top", type=int, default=25, help="with --rank-by-usage")
    parser.add_argument("--usage-days", type=int, default=90)
    parser.add_argument("--no-profile", action="store_true",
                        help="skip cardinality profiling (faster, worse inference)")
    parser.add_argument("--profile-days", type=int, default=90,
                        help="profile only this many recent days; 0 for all history")
    parser.add_argument("--max-dimension-cardinality", type=int, default=500)
    args = parser.parse_args()

    engine = get_engine()
    print(f"engine: {engine.name}", file=sys.stderr)

    if args.rank_by_usage:
        print(f"{'table':<52}{'queries':>10}{'users':>8}  last queried")
        for row in rank_by_usage(engine, args.usage_days, args.top):
            print(f"{str(row[0])[:50]:<52}{row[1]:>10,}{row[2]:>8}  {row[3]}")
        return

    if args.list:
        found = list_tables(engine, args.schema, args.database, args.like)
        for schema, table in found:
            print(f"{schema}.{table}")
        print(f"\n{len(found)} tables", file=sys.stderr)
        return

    if args.tables:
        names = [t.strip() for t in args.tables.split(",") if t.strip()]
    elif args.like or args.schema:
        names = [t for _, t in list_tables(engine, args.schema, args.database, args.like)]
    else:
        parser.error("give --tables, --like or --schema (or use --list)")

    options = Options(max_dimension_cardinality=args.max_dimension_cardinality)
    tables: list[TableInfo] = []
    for table in names:
        print(f"  reading {table}", file=sys.stderr)
        info = describe(engine, table, args.schema, args.database)
        if not args.no_profile:
            profile(engine, info, args.profile_days or None)
        tables.append(info)

    document = build_model(args.name, tables, options)
    text = yaml.safe_dump(document, sort_keys=False, width=100, allow_unicode=True)

    if args.out:
        from pathlib import Path
        Path(args.out).write_text(text, encoding="utf-8")
        n_dims = len(document["dimensions"])
        n_metrics = len(document["metrics"])
        print(
            f"\nwrote {args.out}: {len(tables)} sources, {n_dims} dimensions, "
            f"{n_metrics} metrics - all curated: false",
            file=sys.stderr,
        )
        print("next: delete what is noise, rename what survives, then set "
              "curated: true with an owner and a test.", file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
