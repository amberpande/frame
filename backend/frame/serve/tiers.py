"""L3 — which tier answers this query.

Phase 0 implements two of the three tiers: the result cache and the warehouse.
The cube tiers (server-side DuckDB over Parquet, and the browser cube loaded
into DuckDB-WASM) slot in at the marked seam in Phase 1 without the caller
changing — which is the point of routing through here rather than letting the
API call the engine directly.
"""

from __future__ import annotations

from dataclasses import dataclass

from frame.compile.plan import QueryPlan
from frame.serve.cache import result_cache
from frame.serve.engine import ResultSet, get_engine
from frame.spec.schema import Freshness

# How long a result stays servable, by the freshness the spec declared.
TTL_SECONDS: dict[Freshness, float] = {
    Freshness.daily: 12 * 60 * 60,
    Freshness.hourly: 55 * 60,
    Freshness.near_real_time: 60,
    Freshness.live: 0,  # never cached: one query per viewer, by declaration
}


@dataclass
class ServedResult:
    result: ResultSet
    tier: str
    cached: bool


def serve(plan: QueryPlan, freshness: Freshness) -> ServedResult:
    ttl = TTL_SECONDS.get(freshness, 0)

    if ttl > 0:
        hit = result_cache.get(plan.hash)
        if hit is not None:
            return ServedResult(result=hit, tier="result-cache", cached=True)

    # --- Phase 1 seam -----------------------------------------------------
    # Cube lookup goes here: if a materialized cube covers this plan's grain
    # and its watermark is fresh enough for `freshness`, answer from DuckDB
    # over Parquet and never reach the warehouse. `plan` already carries
    # everything that decision needs.
    # ----------------------------------------------------------------------

    result = get_engine().execute(plan)
    result_cache.put(plan.hash, result, ttl)
    return ServedResult(result=result, tier="warehouse", cached=False)
