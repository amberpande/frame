from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class ColumnMeta:
    name: str
    role: Literal["period", "rank", "dimension", "metric"]
    label: str
    format: dict[str, Any] = field(default_factory=dict)
    direction: str = "neutral"


@dataclass(frozen=True)
class CostEstimate:
    periods: int
    baseline_days: int
    cost_class: str
    row_cap: int

    @property
    def scanned_day_partitions(self) -> int:
        return self.periods + self.baseline_days


@dataclass(frozen=True)
class QueryPlan:
    sql: str
    params: dict[str, Any]
    columns: tuple[ColumnMeta, ...]
    dialect: str
    model_name: str
    model_fingerprint: str
    policy_fingerprint: str
    cost: CostEstimate

    @property
    def hash(self) -> str:
        """The cache key.

        Compiled SQL + bound params + model version + policy fingerprint. Two
        users asking the same question in different words hit the same entry;
        two users with different row access never do.
        """
        payload = {
            "sql": self.sql,
            "params": {k: str(v) for k, v in sorted(self.params.items())},
            "model": self.model_fingerprint,
            "policy": self.policy_fingerprint,
            "dialect": self.dialect,
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()

    @property
    def query_tag(self) -> str:
        """Attached to every warehouse statement so cost is attributable."""
        return f"frame:{self.model_name}:{self.hash[:12]}"
