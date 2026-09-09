import { useEffect, useMemo, useRef, useState } from "react";
import type { DashboardSpec, FilterClause, QueryMeta } from "../spec/types";
import { api } from "./client";
import type { Selection } from "./selection";
import { Table } from "./table";

export interface BlockState {
  table: Table | null;
  meta: QueryMeta | null;
  loading: boolean;
  error: string | null;
  /** Cross-filters currently applied from another block's selection. */
  crossFilters: FilterClause[];
}

const IDLE: BlockState = {
  table: null,
  meta: null,
  loading: false,
  error: null,
  crossFilters: [],
};

/**
 * Turn what the viewer clicked in one block into filters on another.
 *
 * A block declares `source: { block }` and keeps its own `query`; the selected
 * group's dimension values become filter clauses. They are sent as structured
 * clauses and re-validated server-side, so clicking can only ever narrow what
 * a viewer sees — never widen it.
 */
function crossFiltersFor(
  spec: DashboardSpec,
  selections: Record<string, Selection | null>
): Record<string, FilterClause[]> {
  const out: Record<string, FilterClause[]> = {};
  for (const block of spec.blocks) {
    if (!block.query || !block.source) continue;
    const selection = selections[block.source.block];
    if (!selection) {
      out[block.id] = [];
      continue;
    }
    out[block.id] = Object.entries(selection.group.dims)
      .filter(([, value]) => value !== null && value !== undefined)
      .map(([field, value]) => ({ field, op: "eq" as const, value }));
  }
  return out;
}

/**
 * One hook fetches every block, rather than one hook per block.
 *
 * A block that derives from another needs that block's table and compiled SQL,
 * so the data cannot live inside each block's own component. Fetching at the
 * dashboard level also makes the tier mix visible in one place, which is the
 * number the platform is accountable for.
 */
export function useDashboardData(
  spec: DashboardSpec | null,
  params: Record<string, unknown>,
  selections: Record<string, Selection | null> = {}
) {
  const [blocks, setBlocks] = useState<Record<string, BlockState>>({});
  const paramKey = JSON.stringify(params);

  const cross = useMemo(
    () => (spec ? crossFiltersFor(spec, selections) : {}),
    [spec, selections]
  );
  const crossKey = JSON.stringify(cross);

  // A block only pays for `explain` if something actually grounds on its SQL.
  const explainFor = useMemo(() => {
    const wanted = new Set<string>();
    for (const block of spec?.blocks ?? []) {
      if (!block.source || !block.agent) continue;
      if (block.agent.grounding.includes("query.sql")) wanted.add(block.source.block);
    }
    return wanted;
  }, [spec]);

  // Refetching every block whenever any selection changes would be correct but
  // wasteful. Each block gets a signature; only blocks whose signature moved
  // are re-requested.
  const signatures = useRef<Record<string, string>>({});

  useEffect(() => {
    if (!spec) return;
    let cancelled = false;

    const parsedParams = JSON.parse(paramKey);
    const parsedCross: Record<string, FilterClause[]> = JSON.parse(crossKey);
    const queried = spec.blocks.filter((b) => b.query);

    const stale = queried.filter((block) => {
      const signature = `${paramKey}|${JSON.stringify(parsedCross[block.id] ?? [])}`;
      if (signatures.current[block.id] === signature) return false;
      signatures.current[block.id] = signature;
      return true;
    });
    if (!stale.length) return;

    setBlocks((prev) => {
      const next = { ...prev };
      for (const block of stale) {
        next[block.id] = { ...(prev[block.id] ?? IDLE), loading: true, error: null };
      }
      return next;
    });

    for (const block of stale) {
      const filters = parsedCross[block.id] ?? [];
      api
        .blockData(spec.id, block.id, parsedParams, explainFor.has(block.id), filters)
        .then((envelope) => {
          if (cancelled) return;
          setBlocks((prev) => ({
            ...prev,
            [block.id]: {
              table: new Table(envelope),
              meta: envelope.meta,
              loading: false,
              error: null,
              crossFilters: filters,
            },
          }));
        })
        .catch((err: Error) => {
          if (cancelled) return;
          setBlocks((prev) => ({
            ...prev,
            [block.id]: {
              table: null,
              meta: null,
              loading: false,
              error: err.message,
              crossFilters: filters,
            },
          }));
        });
    }

    return () => {
      cancelled = true;
    };
  }, [spec, paramKey, crossKey, explainFor]);

  // A new spec must not inherit the previous one's signatures.
  useEffect(() => {
    signatures.current = {};
    setBlocks({});
  }, [spec?.id]);

  const states = Object.values(blocks);
  return {
    blocks,
    loading: states.some((s) => s.loading),
    /** The mix the platform is accountable for. */
    tiers: states.reduce<Record<string, number>>((acc, s) => {
      if (s.meta) acc[s.meta.tier] = (acc[s.meta.tier] ?? 0) + 1;
      return acc;
    }, {}),
    slowestMs: Math.max(0, ...states.map((s) => s.meta?.elapsedMs ?? 0)),
  };
}

export function blockState(
  blocks: Record<string, BlockState>,
  id: string | undefined
): BlockState {
  if (!id) return IDLE;
  return blocks[id] ?? IDLE;
}
