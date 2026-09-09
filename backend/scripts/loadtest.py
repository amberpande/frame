"""Load test: simulate concurrent viewers opening dashboards.

Measures the two numbers that decide whether a deployment scales:

  * requests per second the service sustains, and p50/p95/p99 latency
  * **warehouse round-trips per dashboard load** — the number that decides
    whether 10,000 users is affordable or ruinous

The second matters more. Throughput can be bought with more tasks; warehouse
round-trips are paid for in credits and are capped by warehouse concurrency,
so any per-request round-trip is a hard ceiling on how far the platform scales.

    python scripts/loadtest.py --users 50 --loads 4
    python scripts/loadtest.py --spec ops-control-tower --users 100 --loads 2
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "http://127.0.0.1:8000/api/v1"


def _get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.load(r)


def _post(path: str, body: dict) -> tuple[int, float]:
    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        BASE + path, data=payload,
        headers={"Content-Type": "application/json", "X-Frame-Identity": "analyst"},
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        e.read()
        status = e.code
    return status, (time.perf_counter() - started) * 1000


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", default="ops-control-tower")
    ap.add_argument("--users", type=int, default=50, help="concurrent viewers")
    ap.add_argument("--loads", type=int, default=4, help="dashboard loads per viewer")
    ap.add_argument("--label", default="", help="printed with the results")
    args = ap.parse_args()

    spec = _get(f"/specs/{args.spec}")
    blocks = [b["id"] for b in spec["blocks"] if b.get("query")]
    print(f"spec {args.spec}: {len(blocks)} querying blocks")
    print(f"{args.users} concurrent viewers x {args.loads} loads "
          f"= {args.users * args.loads * len(blocks):,} block requests\n")

    before = _get("/health")

    def one_load(_: int) -> list[tuple[int, float]]:
        """A viewer opening the dashboard: every block fetched at once."""
        with ThreadPoolExecutor(max_workers=len(blocks)) as pool:
            return list(pool.map(
                lambda b: _post(f"/specs/{args.spec}/blocks/{b}/data", {"params": {}}),
                blocks,
            ))

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.users) as pool:
        batches = list(pool.map(one_load, range(args.users * args.loads)))
    elapsed = time.perf_counter() - started

    after = _get("/health")

    results = [r for batch in batches for r in batch]
    latencies = sorted(ms for _, ms in results)
    failures = [s for s, _ in results if s >= 400]
    n_loads = args.users * args.loads

    wh_before = before.get("warehouse", {})
    wh_after = after.get("warehouse", {})
    executes = wh_after.get("executes", 0) - wh_before.get("executes", 0)
    scalars = wh_after.get("scalars", 0) - wh_before.get("scalars", 0)
    round_trips = executes + scalars

    def pct(p: float) -> float:
        return latencies[min(int(len(latencies) * p), len(latencies) - 1)]

    print(f"--- {args.label or 'results'} " + "-" * max(0, 46 - len(args.label)))
    print(f"  requests          {len(results):,} in {elapsed:.1f}s")
    print(f"  throughput        {len(results) / elapsed:,.0f} req/s"
          f"   ({n_loads / elapsed:.1f} dashboard loads/s)")
    print(f"  failures          {len(failures)}")
    print(f"  latency p50/p95/p99  {pct(.50):.0f} / {pct(.95):.0f} / {pct(.99):.0f} ms")
    print(f"  cache hit rate    {after['cache']['hit_rate']:.1%}")
    print()
    print(f"  warehouse round-trips      {round_trips:,}"
          f"  ({executes:,} query, {scalars:,} scalar)")
    print(f"  per dashboard load         {round_trips / n_loads:.2f}")
    print(f"  per block request          {round_trips / len(results):.3f}")

    # At 10k users the extrapolation is the whole point.
    per_load = round_trips / n_loads
    print()
    print("  extrapolated to 10,000 concurrent viewers")
    print("  (6 dashboard loads per viewer per hour = 16.7 loads/s):")
    print(f"     warehouse queries/s      {16.7 * per_load:,.1f}")
    verdict = ("comfortable on one XS multi-cluster warehouse"
               if 16.7 * per_load < 20 else
               "TOO HIGH - no warehouse configuration serves this")
    print(f"     verdict                  {verdict}")


if __name__ == "__main__":
    main()
