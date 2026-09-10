"""L4 — the spec schema.

A dashboard is this document. The renderer draws it, the builder edits it, the
agent writes it, and the compiler turns its `query` objects into SQL. One
definition, four consumers; generate the TypeScript types from this file rather
than hand-maintaining a parallel copy.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SPEC_VERSION = 1


class Freshness(str, Enum):
    """Picks the serving tier. See frame.serve.tiers."""

    daily = "daily"  # compiled to a cube, served from the browser
    hourly = "hourly"  # server-side cube
    near_real_time = "near_real_time"  # result cache, short TTL
    live = "live"  # straight to the warehouse, one query per viewer


class Base(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Placement(Base):
    x: int = Field(ge=0, le=11)
    y: int = Field(ge=0)
    w: int = Field(ge=1, le=12)
    h: int = Field(ge=1)

    @model_validator(mode="after")
    def _fits(self) -> Placement:
        if self.x + self.w > 12:
            raise ValueError(f"block overflows the 12-column grid: x={self.x} w={self.w}")
        return self


class FilterClause(Base):
    field: str
    op: Literal["eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte", "contains"] = "eq"
    value: Any = None


class SortSpec(Base):
    by: str
    dir: Literal["asc", "desc"] = "desc"
    # Rank on absolute value. Severity is signed, so a large improvement must
    # rank alongside a large regression rather than sinking to the bottom.
    abs: bool = False


class QuerySpec(Base):
    metrics: list[str] = Field(min_length=1)
    by: list[str] = Field(default_factory=list)
    filters: list[FilterClause] = Field(default_factory=list)
    # A param reference ("$compare_to") or a literal date. Present means the
    # query returns two observations per group, tagged in the __period column.
    compare: str | None = None
    # How far back a time series reaches. Only meaningful when a time dimension
    # appears in `by`: without it the query is "as of one date" and grouping by
    # date would return exactly that date. Explicit rather than inferred,
    # because the window is what the query costs.
    window_days: int | None = Field(default=None, ge=2, le=1826, alias="windowDays")
    limit: int | None = Field(default=None, ge=1)
    order: SortSpec | None = None


class BlockSource(Base):
    """Wires one block's selection into another block."""

    block: str
    on: Literal["select", "hover", "always"] = "select"


class AgentBinding(Base):
    task: str
    grounding: list[
        Literal["query.sql", "query.result", "model.definitions", "block.selection"]
    ] = Field(default_factory=list)


class SqlSource(Base):
    """Hand-written SQL for a scratchpad block.

    Not governed: no grain, no declared metrics, no compiler. It executes under
    the viewer's own warehouse role, so what it can read is bounded by their
    grants rather than by anything in this codebase. A block carrying one is
    marked as ungoverned wherever it appears.
    """

    sql: str = Field(min_length=1, max_length=20000)
    # Why this is not a governed metric. Not enforced, but a spec full of
    # unexplained SQL blocks is the signal that the model is missing something.
    note: str | None = None


class Block(Base):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    viz: str
    at: Placement
    title: str | None = None
    subtitle: str | None = None
    query: QuerySpec | None = None
    # Exactly one of `query`, `sql` or `source` drives a block.
    sql: SqlSource | None = None
    encode: dict[str, str] = Field(default_factory=dict)
    sort: SortSpec | None = None
    source: BlockSource | None = None
    agent: AgentBinding | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class Param(Base):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_]*$")
    type: Literal["date", "dimension", "measure", "string", "number", "boolean"]
    label: str | None = None
    default: Any = None
    of: str | None = None  # for type=dimension: which dimension it filters
    multi: bool = False


class CalculatedMetric(Base):
    """A metric defined by a dashboard, not by the semantic model.

    Scoped to this spec: it cannot be referenced from anywhere else, so it
    cannot pollute the shared namespace. That is what makes it safe to let a
    dashboard author create one without review.

    It may only be an expression over metrics that already exist — no columns,
    no tables, no joins, no aggregates. A calculation that needs any of those
    is a *measure*, and a measure belongs in the model where it gets a grain,
    an owner and a test. See frame.semantic.expr for what is permitted.

    The `calc.` prefix is required so that reading any dashboard tells you at a
    glance which of its metrics are governed and which are not.
    """

    name: str = Field(pattern=r"^calc\.[a-z][a-z0-9_]*$")
    label: str
    expr: str = Field(min_length=1, max_length=1000)
    format: dict[str, Any] = Field(default_factory=dict)
    direction: Literal["higher_is_better", "lower_is_better", "neutral"] = "neutral"
    description: str | None = None


class DashboardSpec(Base):
    # Points editors and coding agents at schemas/spec.schema.json so a spec
    # gets completion and validation while it is being written, rather than a
    # 422 after it is published.
    schema_ref: str | None = Field(default=None, alias="$schema")
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    spec_version: int = Field(default=SPEC_VERSION, alias="specVersion")
    model: str
    title: str
    description: str | None = None
    freshness: Freshness = Freshness.daily
    # `live` bypasses every tier and bills one warehouse query per viewer, so
    # it has to be argued for in writing rather than left as a default.
    justification: str | None = None
    owner: str | None = None
    tags: list[str] = Field(default_factory=list)
    params: list[Param] = Field(default_factory=list)
    # Dashboard-local calculations. Promote one into the semantic model when it
    # proves useful to more than this dashboard.
    metrics: list[CalculatedMetric] = Field(default_factory=list)
    blocks: list[Block] = Field(min_length=1)

    @model_validator(mode="after")
    def _coherent(self) -> DashboardSpec:
        seen: set[str] = set()
        for block in self.blocks:
            if block.id in seen:
                raise ValueError(f"duplicate block id: {block.id}")
            seen.add(block.id)

        for block in self.blocks:
            if block.source and block.source.block not in seen:
                raise ValueError(
                    f"block {block.id!r} sources from unknown block {block.source.block!r}"
                )
            if block.source and block.source.block == block.id:
                raise ValueError(f"block {block.id!r} sources from itself")
            if block.query is not None and block.sql is not None:
                raise ValueError(
                    f"block {block.id!r} has both a governed query and raw SQL; "
                    "it can have one or the other"
                )
            if block.query is None and block.sql is None and block.source is None:
                raise ValueError(
                    f"block {block.id!r} has no query, no SQL and no source block"
                )

        param_names = {p.name for p in self.params}
        for block in self.blocks:
            if block.query and block.query.compare and block.query.compare.startswith("$"):
                ref = block.query.compare[1:]
                if ref not in param_names:
                    raise ValueError(f"block {block.id!r} compares to unknown param ${ref}")

        calc_names: set[str] = set()
        for calc in self.metrics:
            if calc.name in calc_names:
                raise ValueError(f"duplicate calculated metric: {calc.name}")
            calc_names.add(calc.name)

        if self.freshness is Freshness.live and not self.justification:
            raise ValueError(
                "freshness 'live' bills one warehouse query per viewer and needs a "
                "`justification` saying why a cached tier will not do"
            )
        return self

    def block(self, block_id: str) -> Block:
        for b in self.blocks:
            if b.id == block_id:
                return b
        raise KeyError(block_id)
