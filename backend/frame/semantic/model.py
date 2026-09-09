"""L1 — the semantic model.

The platform's whole vocabulary. Everything above this layer is a consumer:
the compiler reads it to emit SQL, the builder reads it to offer drop targets,
and the agent is permitted to reference nothing outside it.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

METRIC_REF = re.compile(r"\{([a-zA-Z0-9_.]+)(?:@([a-zA-Z0-9_]+))?\}")


class Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(Base):
    name: str = ""
    relation: str  # fully qualified, what ships to Snowflake
    local: str | None = None  # DuckDB fixture name for development
    # Optional. Many of the tables in a real warehouse are dimensions or
    # snapshots with no date at all; those simply cannot be compared across
    # dates or charted as a series, and the guard says so.
    time_column: str | None = None
    # False means introspected but not yet reviewed by a human.
    curated: bool = True
    row_estimate: int | None = None
    description: str | None = None


class Dimension(Base):
    name: str
    label: str
    source: str
    column: str
    kind: Literal["categorical", "time"] = "categorical"
    synonyms: list[str] = Field(default_factory=list)
    description: str | None = None
    curated: bool = True
    # Approximate distinct count from profiling. High cardinality is not an
    # error, but grouping by a million-value column is a cost decision.
    cardinality: int | None = None


class Baseline(Base):
    """Rolling statistics the compiler materializes alongside a measure.

    Declaring it here is what lets `severity.signed_z` be a governed definition
    rather than logic re-implemented in each dashboard's renderer code.
    """

    window_days: int = Field(ge=2, le=730)
    stats: list[Literal["avg", "stddev", "median", "min", "max"]]


class Metric(Base):
    name: str
    label: str
    kind: Literal["measure", "derived"] = "measure"

    # measure
    source: str | None = None
    agg: Literal["sum", "avg", "min", "max", "count", "count_distinct"] | None = None
    column: str | None = None
    filters: list[str] = Field(default_factory=list)
    baseline: Baseline | None = None

    # derived
    expr: str | None = None

    grain: list[str] = Field(default_factory=list)
    format: dict[str, Any] = Field(default_factory=dict)
    owner: str = "unowned"
    tests: list[str] = Field(default_factory=list)
    cost_class: Literal["cheap", "moderate", "expensive"] = "cheap"
    direction: Literal["higher_is_better", "lower_is_better", "neutral"] = "neutral"
    synonyms: list[str] = Field(default_factory=list)
    note: str | None = None

    # False means introspected but not yet reviewed. Draft metrics are legal
    # so a dashboard can be built the day the warehouse is connected; the
    # count of them is the curation debt, and it is reportable.
    curated: bool = True

    # COUNT(DISTINCT) on a high-cardinality column is one of the most
    # expensive things a warehouse can be asked to do. HyperLogLog is
    # typically within a fraction of a percent and dramatically cheaper.
    approx: bool = False

    @model_validator(mode="after")
    def _shape(self) -> Metric:
        if self.kind == "measure":
            if not (self.source and self.agg):
                raise ValueError(f"measure {self.name!r} needs both `source` and `agg`")
            if self.agg != "count" and not self.column:
                raise ValueError(f"measure {self.name!r} needs a `column` for agg={self.agg}")
        else:
            if not self.expr:
                raise ValueError(f"derived metric {self.name!r} needs an `expr`")
            if self.baseline is not None:
                raise ValueError(
                    f"derived metric {self.name!r} cannot declare a baseline; "
                    "declare it on the measure it references"
                )
        if self.curated and not self.tests:
            raise ValueError(
                f"metric {self.name!r} is curated but has no tests — a curated metric "
                "needs at least one, or the semantic layer becomes a dumping ground. "
                "Set `curated: false` if it is still an introspected draft."
            )
        if self.approx and self.agg != "count_distinct":
            raise ValueError(
                f"metric {self.name!r} sets approx but agg is {self.agg!r}; "
                "approximation only applies to count_distinct"
            )
        return self

    def references(self) -> list[tuple[str, str | None]]:
        """(metric name, baseline stat) pairs this derived metric depends on."""
        if self.kind != "derived" or not self.expr:
            return []
        return [(m.group(1), m.group(2)) for m in METRIC_REF.finditer(self.expr)]


class SemanticModel(Base):
    name: str
    version: int = 1
    label: str | None = None
    description: str | None = None
    sources: dict[str, Source]
    dimensions: list[Dimension]
    metrics: list[Metric]

    @model_validator(mode="after")
    def _resolve(self) -> SemanticModel:
        for key, src in self.sources.items():
            if not src.name:
                src.name = key

        dim_names = {d.name for d in self.dimensions}
        for dim in self.dimensions:
            if dim.source not in self.sources:
                raise ValueError(f"dimension {dim.name!r} references unknown source {dim.source!r}")

        metric_names = {m.name for m in self.metrics}
        for metric in self.metrics:
            if metric.kind == "measure" and metric.source not in self.sources:
                raise ValueError(
                    f"metric {metric.name!r} references unknown source {metric.source!r}"
                )
            for gd in metric.grain:
                if gd not in dim_names:
                    raise ValueError(
                        f"metric {metric.name!r} declares grain on unknown dimension {gd!r}"
                    )
            for ref, stat in metric.references():
                if ref not in metric_names:
                    raise ValueError(
                        f"derived metric {metric.name!r} references unknown metric {ref!r}"
                    )
                if stat:
                    target = next(m for m in self.metrics if m.name == ref)
                    expected = {
                        f"{s}_{target.baseline.window_days}d"
                        for s in (target.baseline.stats if target.baseline else [])
                    }
                    if stat not in expected:
                        raise ValueError(
                            f"derived metric {metric.name!r} wants baseline stat {stat!r} "
                            f"from {ref!r}, which publishes {sorted(expected) or 'none'}"
                        )
        return self

    # -- lookups -----------------------------------------------------------

    def metric(self, name: str) -> Metric:
        for m in self.metrics:
            if m.name == name:
                return m
        raise KeyError(f"unknown metric {name!r} in model {self.name!r}")

    def dimension(self, name: str) -> Dimension:
        for d in self.dimensions:
            if d.name == name:
                return d
        raise KeyError(f"unknown dimension {name!r} in model {self.name!r}")

    def has_metric(self, name: str) -> bool:
        return any(m.name == name for m in self.metrics)

    def has_dimension(self, name: str) -> bool:
        return any(d.name == name for d in self.dimensions)

    def base_metrics(self, name: str) -> list[Metric]:
        """Flatten a metric to the measures that actually hit a table."""
        metric = self.metric(name)
        if metric.kind == "measure":
            return [metric]
        out: list[Metric] = []
        for ref, _stat in metric.references():
            for base in self.base_metrics(ref):
                if base.name not in {m.name for m in out}:
                    out.append(base)
        return out

    def effective_grain(self, name: str) -> set[str]:
        """Dimensions a metric may legally be sliced by."""
        metric = self.metric(name)
        if metric.kind == "measure":
            return set(metric.grain)
        grains = [set(b.grain) for b in self.base_metrics(name)]
        return set.intersection(*grains) if grains else set()

    def fingerprint(self) -> str:
        """Part of every cache key: a model change must invalidate results."""
        payload = self.model_dump(mode="json")
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()[:16]
