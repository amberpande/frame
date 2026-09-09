from __future__ import annotations

import os
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_ROOT.parent

MODELS_DIR = Path(os.environ.get("FRAME_MODELS_DIR", BACKEND_ROOT / "models"))
SPECS_DIR = Path(os.environ.get("FRAME_SPECS_DIR", BACKEND_ROOT / "specs"))
DATA_DIR = Path(os.environ.get("FRAME_DATA_DIR", BACKEND_ROOT / "data"))

# Engine selection. "duckdb" runs the whole stack against the local fixture so
# development needs no warehouse credentials; "snowflake" reads the standard
# SNOWFLAKE_* environment variables.
ENGINE = os.environ.get("FRAME_ENGINE", "duckdb")
DUCKDB_PATH = Path(os.environ.get("FRAME_DUCKDB_PATH", DATA_DIR / "frame.duckdb"))

# Hard ceiling the compiler will not emit past, whatever a spec asks for.
MAX_ROWS = int(os.environ.get("FRAME_MAX_ROWS", "50000"))

# Statement timeout pushed down to the warehouse on the interactive path.
STATEMENT_TIMEOUT_SECONDS = int(os.environ.get("FRAME_STATEMENT_TIMEOUT", "30"))

# A source bigger than this, queried with no time predicate and no filters, is
# refused rather than run. Against an unmodelled warehouse this is the single
# most useful cost protection there is.
LARGE_TABLE_ROWS = int(os.environ.get("FRAME_LARGE_TABLE_ROWS", "50000000"))

# The shared result cache. MUST be a managed Redis/Valkey reachable from every
# task - not a sidecar, and not inside the application container. Unset means a
# per-task cache, which is correct for one task and wrong the moment you scale
# out: warehouse load multiplies by the task count.
REDIS_URL = os.environ.get("FRAME_REDIS_URL", "")
REDIS_TIMEOUT_SECONDS = float(os.environ.get("FRAME_REDIS_TIMEOUT", "0.25"))

# L1 is a per-task convenience in front of the shared cache, deliberately small
# and short-lived so tasks cannot drift apart on freshness.
CACHE_L1_ENTRIES = int(os.environ.get("FRAME_CACHE_L1_ENTRIES", "512"))
CACHE_L1_TTL_SECONDS = float(os.environ.get("FRAME_CACHE_L1_TTL", "15"))

# How long a source's max-date watermark is reused before re-reading it.
# Resolving @latest_close per request puts a warehouse round-trip in front of
# the cache, which caps concurrency no matter how well the cache performs.
WATERMARK_TTL_SECONDS = float(os.environ.get("FRAME_WATERMARK_TTL", "60"))

# Heavier work is routed to its own warehouse so an expensive block cannot
# queue ahead of a cheap one on the interactive cluster.
SNOWFLAKE_WAREHOUSE_HEAVY = os.environ.get("FRAME_SNOWFLAKE_WAREHOUSE_HEAVY", "")

CORS_ORIGINS = os.environ.get(
    "FRAME_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(",")
