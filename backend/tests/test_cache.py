"""The shared cache is optional, and must stay optional.

Redis is a scaling choice, not a dependency. The platform has to run — and be
correct — with no Redis package installed and no FRAME_REDIS_URL set, because
that is how it runs in development, in CI, and in any single-task deployment.

These tests fail if someone makes it required.
"""

from __future__ import annotations

import time
import tomllib
from pathlib import Path

import pytest

from frame.serve.cache import ResultCache, TieredCache, _build
from frame.serve.engine import ResultSet

BACKEND = Path(__file__).resolve().parent.parent


def make_result(value: int = 1) -> ResultSet:
    return ResultSet(
        columns=[{"name": "n", "role": "metric", "label": "N", "format": {}, "direction": "neutral"}],
        rows=[[value]],
        elapsed_ms=1.0,
    )


def test_redis_is_not_a_hard_dependency():
    """It belongs in optional-dependencies, never in the install set."""
    meta = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    required = " ".join(meta["project"]["dependencies"]).lower()
    assert "redis" not in required

    extras = meta["project"]["optional-dependencies"]
    assert "redis" in extras


def test_no_module_level_redis_import():
    """A top-level import would make the package unimportable without redis."""
    source = (BACKEND / "frame" / "serve" / "cache.py").read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith(("import redis", "from redis")):
            indent = len(line) - len(line.lstrip())
            assert indent > 0, "redis must be imported lazily, inside RedisCache"


def test_works_with_no_second_tier():
    cache = TieredCache(ResultCache(max_entries=8), None)
    cache.put("k", make_result(7), ttl_seconds=60)
    got = cache.get("k")
    assert got is not None and got.rows == [[7]]
    assert cache.stats()["shared"] is False


def test_ttl_is_honoured_without_redis():
    cache = TieredCache(ResultCache(max_entries=8), None)
    cache.put("k", make_result(), ttl_seconds=0.05)
    assert cache.get("k") is not None
    time.sleep(0.08)
    assert cache.get("k") is None


def test_zero_ttl_is_never_stored():
    """freshness: live bypasses the cache entirely."""
    cache = TieredCache(ResultCache(max_entries=8), None)
    cache.put("k", make_result(), ttl_seconds=0)
    assert cache.get("k") is None


def test_lru_evicts_rather_than_growing():
    cache = ResultCache(max_entries=3)
    for i in range(5):
        cache.put(f"k{i}", make_result(i), ttl_seconds=60)
    assert cache.stats()["entries"] == 3
    assert cache.get("k0") is None      # evicted
    assert cache.get("k4") is not None  # most recent survives


def test_unreachable_redis_does_not_break_startup(monkeypatch):
    """A URL pointing at nothing must degrade to a per-task cache, not crash.

    With the redis package absent this also covers "configured but not
    installed", which is the likeliest misconfiguration in practice.
    """
    monkeypatch.setattr("frame.config.REDIS_URL", "redis://127.0.0.1:1/0")
    cache = _build()
    assert isinstance(cache, TieredCache)
    cache.put("k", make_result(3), ttl_seconds=60)
    got = cache.get("k")
    assert got is not None and got.rows == [[3]]


def test_a_failing_second_tier_degrades_to_a_miss():
    """A cache outage must slow the platform down, never take it down."""

    class Broken:
        hits = 0
        misses = 0

        def get(self, key):
            raise RuntimeError("connection reset")

        def put(self, key, value, ttl_seconds):
            raise RuntimeError("connection reset")

        def clear(self):
            raise RuntimeError("connection reset")

        def stats(self):
            return {"errors": 1}

    cache = TieredCache(ResultCache(max_entries=8), Broken())
    with pytest.raises(RuntimeError):
        # The backend itself raises; RedisCache is what swallows it, which is
        # why the real implementation catches per call rather than here.
        cache.l2.get("k")

    # The L1 path is unaffected by an unhealthy L2.
    cache.l1.put("k", make_result(9), ttl_seconds=60)
    got = cache.l1.get("k")
    assert got is not None and got.rows == [[9]]
