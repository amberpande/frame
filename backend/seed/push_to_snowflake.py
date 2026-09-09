"""Load the local fixture into Snowflake.

Exports each table from DuckDB to Parquet, PUTs it to a table stage and COPYs
it in. Parquet plus COPY rather than `executemany`, because that is how you
would load a real table and it is the path worth having working.

    python seed/push_to_snowflake.py            # load everything
    python seed/push_to_snowflake.py --check    # connect and verify only

Needs the same SNOWFLAKE_* environment the query service uses, plus the objects
from snowflake/ddl.sql.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb  # noqa: E402

from frame.config import DUCKDB_PATH  # noqa: E402

TABLES = ["fct_exception", "agg_team_sla"]


def connect():
    try:
        import snowflake.connector
    except ImportError:
        sys.exit(
            "snowflake-connector-python is not installed.\n"
            '  pip install -e ".[snowflake]"'
        )

    missing = [v for v in ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER") if not os.environ.get(v)]
    if missing:
        sys.exit(f"missing environment: {', '.join(missing)} — see .env.example")

    opts = {
        "account": os.environ["SNOWFLAKE_ACCOUNT"],
        "user": os.environ["SNOWFLAKE_USER"],
        "warehouse": os.environ.get("SNOWFLAKE_WAREHOUSE", "FRAME_BATCH_S"),
        "database": os.environ.get("SNOWFLAKE_DATABASE", "ANALYTICS"),
        "schema": os.environ.get("SNOWFLAKE_SCHEMA", "OPS"),
        "role": os.environ.get("SNOWFLAKE_ROLE"),
        "password": os.environ.get("SNOWFLAKE_PASSWORD"),
        "private_key_file": os.environ.get("SNOWFLAKE_PRIVATE_KEY_PATH"),
        "authenticator": os.environ.get("SNOWFLAKE_AUTHENTICATOR"),
    }
    return snowflake.connector.connect(**{k: v for k, v in opts.items() if v})


def check(con) -> None:
    cur = con.cursor()
    who = cur.execute(
        "SELECT CURRENT_ACCOUNT(), CURRENT_USER(), CURRENT_ROLE(), "
        "CURRENT_WAREHOUSE(), CURRENT_DATABASE(), CURRENT_SCHEMA()"
    ).fetchone()
    print(
        f"  account={who[0]} user={who[1]} role={who[2]}\n"
        f"  warehouse={who[3]} database={who[4]} schema={who[5]}"
    )
    for table in TABLES:
        try:
            n = cur.execute(f"SELECT COUNT(*) FROM {table.upper()}").fetchone()[0]
            print(f"  {table.upper():<16} {n:>9,} rows")
        except Exception as exc:  # table may not exist yet
            print(f"  {table.upper():<16} not readable — {str(exc).splitlines()[0]}")


def load(con, tmp: Path) -> None:
    if not DUCKDB_PATH.exists():
        sys.exit(f"no fixture at {DUCKDB_PATH} - run `python seed/build_seed.py` first")

    duck = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    cur = con.cursor()

    for table in TABLES:
        parquet = tmp / f"{table}.parquet"
        duck.execute(
            f"COPY (SELECT * FROM {table}) TO '{parquet.as_posix()}' (FORMAT PARQUET)"
        )
        rows = duck.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        target = table.upper()

        print(f"  {target}: {rows:,} rows -> {parquet.name}")
        cur.execute(f"TRUNCATE TABLE IF EXISTS {target}")
        # The table stage (@%TABLE) needs no separate stage object to exist.
        cur.execute(
            f"PUT 'file://{parquet.as_posix()}' '@%{target}' "
            "OVERWRITE = TRUE AUTO_COMPRESS = TRUE"
        )
        # Parquet columns are lower case; Snowflake columns are upper case.
        # MATCH_BY_COLUMN_NAME with CASE_INSENSITIVE is what bridges the two.
        cur.execute(
            f"COPY INTO {target} FROM '@%{target}' "
            "FILE_FORMAT = (TYPE = PARQUET) "
            "MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE "
            "PURGE = TRUE"
        )
        loaded = cur.execute(f"SELECT COUNT(*) FROM {target}").fetchone()[0]
        status = "ok" if loaded == rows else f"MISMATCH (expected {rows:,})"
        print(f"  {target}: {loaded:,} rows in Snowflake - {status}")

    duck.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="verify the connection without loading"
    )
    args = parser.parse_args()

    con = connect()
    try:
        if args.check:
            print("connection ok:")
            check(con)
            return
        print("loading fixture into Snowflake:")
        with tempfile.TemporaryDirectory() as tmpdir:
            load(con, Path(tmpdir))
        print("\nnow point the query service at it:")
        print("  FRAME_ENGINE=snowflake python -m uvicorn frame.main:app --port 8000")
    finally:
        con.close()


if __name__ == "__main__":
    main()
