"""L3 — the result cache.

Two tiers, one key.

  L1  in-process LRU     microseconds, per task, absorbs repeat hits
  L2  Redis / Valkey     sub-millisecond, SHARED ACROSS EVERY TASK

L2 is the one that matters, and it must not live inside the application
container. A cache co-located with the app is a cache per task: eight tasks
means eight independent caches, so a cold entry is fetched from the warehouse
up to eight times instead of once. Measured warehouse load at 10,000 users goes
from 8.3 queries/second with a shared cache to 66.8 with per-task caches — and
tasks are added precisely when load is already high, so the miss storm arrives
at the worst moment. Rolling deploys make it worse again by replacing every
task, and therefore every cache, at the same instant.

Run Redis as a managed service (ElastiCache / Valkey) in the same VPC, reachable
from the task security group. Never as a sidecar.

The key is `QueryPlan.hash` in both tiers, unchanged: compiled SQL + bound
params + semantic model fingerprint + the caller's policy fingerprint.
"""

from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Protocol

from frame import config
from frame.serve.engine import ResultSet


@dataclass
class CacheEntry:
    value: ResultSet
    expires_at: float


class CacheBackend(Protocol):
    def get(self, key: str) -> ResultSet | None: ...
    def put(self, key: str, value: ResultSet, ttl_seconds: float) -> None: ...
    def clear(self) -> None: ...
    def stats(self) -> dict[str, Any]: ...


# --------------------------------------------------------------- L1, in-process

class ResultCache:
    """In-process LRU with per-entry TTL.

    Useful even with Redis behind it: a dashboard load asks for overlapping
    plans, and a local hit costs a dictionary lookup rather than a network
    round-trip. It is not a substitute for L2, because it is per task.
    """

    def __init__(self, max_entries: int | None = None) -> None:
        self._store: OrderedDict[str, CacheEntry] = OrderedDict()
        self._max = max_entries or config.CACHE_L1_ENTRIES
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> ResultSet | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self.misses += 1
                return None
            if entry.expires_at < time.time():
                del self._store[key]
                self.misses += 1
                return None
            self._store.move_to_end(key)
            self.hits += 1
            return entry.value

    def put(self, key: str, value: ResultSet, ttl_seconds: float) -> None:
        if ttl_seconds <= 0:
            return
        with self._lock:
            self._store[key] = CacheEntry(value=value, expires_at=time.time() + ttl_seconds)
            self._store.move_to_end(key)
            while len(self._store) > self._max:
                self._store.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def stats(self) -> dict[str, Any]:
        total = self.hits + self.misses
        return {
            "entries": len(self._store),
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hits / total, 4) if total else 0.0,
        }


# ------------------------------------------------------------------ L2, shared

def _encode(value: ResultSet) -> bytes:
    return json.dumps(
        {"columns": value.columns, "rows": value.rows, "elapsed_ms": value.elapsed_ms},
        separators=(",", ":"),
    ).encode()


def _decode(blob: bytes) -> ResultSet:
    raw = json.loads(blob)
    return ResultSet(
        columns=raw["columns"], rows=raw["rows"], elapsed_ms=raw.get("elapsed_ms", 0.0)
    )


class RedisCache:
    """Shared result cache.

    Every failure degrades to a miss rather than an error: a cache outage must
    slow the platform down, never take it down.
    """

    def __init__(self, url: str, prefix: str = "frame:res:") -> None:
        import redis  # imported lazily so the dependency stays optional

        self._client = redis.Redis.from_url(
            url,
            socket_timeout=config.REDIS_TIMEOUT_SECONDS,
            socket_connect_timeout=config.REDIS_TIMEOUT_SECONDS,
            retry_on_timeout=False,
            health_check_interval=30,
        )
        self._prefix = prefix
        self.hits = 0
        self.misses = 0
        self.errors = 0

    def get(self, key: str) -> ResultSet | None:
        try:
            blob = self._client.get(self._prefix + key)
        except Exception:
            self.errors += 1
            return None
        if blob is None:
            self.misses += 1
            return None
        try:
            value = _decode(blob)
        except Exception:  # a poisoned entry is a miss, not an outage
            self.errors += 1
            return None
        self.hits += 1
        return value

    def put(self, key: str, value: ResultSet, ttl_seconds: float) -> None:
        if ttl_seconds <= 0:
            return
        try:
            self._client.setex(self._prefix + key, int(ttl_seconds), _encode(value))
        except Exception:
            self.errors += 1

    def clear(self) -> None:
        try:
            for chunk in self._client.scan_iter(match=self._prefix + "*", count=500):
                self._client.delete(chunk)
        except Exception:
            self.errors += 1

    def stats(self) -> dict[str, Any]:
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "errors": self.errors,
            "hit_rate": round(self.hits / total, 4) if total else 0.0,
        }


# ------------------------------------------------------------------- composed

class TieredCache:
    """L1 in front of L2. A hit in either populates the one above it."""

    def __init__(self, l1: ResultCache, l2: CacheBackend | None = None) -> None:
        self.l1 = l1
        self.l2 = l2

    def get(self, key: str) -> ResultSet | None:
        value = self.l1.get(key)
        if value is not None:
            return value
        if self.l2 is None:
            return None
        value = self.l2.get(key)
        if value is not None:
            # Promote, but only for a short window: L1 must not hold an entry
            # long after L2 has expired it, or tasks drift apart on freshness.
            self.l1.put(key, value, config.CACHE_L1_TTL_SECONDS)
        return value

    def put(self, key: str, value: ResultSet, ttl_seconds: float) -> None:
        self.l1.put(key, value, min(ttl_seconds, config.CACHE_L1_TTL_SECONDS))
        if self.l2 is not None:
            self.l2.put(key, value, ttl_seconds)

    def clear(self) -> None:
        self.l1.clear()
        if self.l2 is not None:
            self.l2.clear()

    @property
    def hits(self) -> int:
        return self.l1.hits + (self.l2.hits if self.l2 else 0)

    @property
    def misses(self) -> int:
        return self.l2.misses if self.l2 else self.l1.misses

    def stats(self) -> dict[str, Any]:
        total = self.hits + self.misses
        out: dict[str, Any] = {
            "shared": self.l2 is not None,
            "entries": len(self.l1._store),
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hits / total, 4) if total else 0.0,
            "l1": self.l1.stats(),
        }
        if self.l2 is not None:
            out["l2"] = self.l2.stats()
        return out


def _build() -> TieredCache:
    l1 = ResultCache()
    if not config.REDIS_URL:
        # Correct for one task, and the reason the capacity plan says to set
        # FRAME_REDIS_URL before scaling out.
        return TieredCache(l1, None)
    try:
        return TieredCache(l1, RedisCache(config.REDIS_URL))
    except Exception as exc:  # never fail startup over a cache
        import sys

        print(
            f"warning: FRAME_REDIS_URL is set but Redis is unavailable ({exc}). "
            "Falling back to a per-task cache; do not scale out in this state.",
            file=sys.stderr,
        )
        return TieredCache(l1, None)


result_cache = _build()
