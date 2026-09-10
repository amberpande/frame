import { useCallback, useMemo, useState } from "react";
import { api } from "../runtime/client";
import type { Block, CalculatedMetric, DashboardSpec, Placement } from "../spec/types";
import { manifests } from "../viz/manifests";
import { pruneOptions, type ResolvedOptions } from "../viz/options";

export interface Editor {
  editing: boolean;
  draft: DashboardSpec | null;
  dirty: boolean;
  selectedId: string | null;
  saving: boolean;
  error: string | null;

  start: () => void;
  startBlank: (id: string, title: string, model: string) => void;
  cancel: () => void;
  save: () => Promise<void>;
  select: (blockId: string | null) => void;

  patchBlock: (blockId: string, patch: Partial<Block>) => void;
  setOptions: (blockId: string, options: ResolvedOptions) => void;
  place: (blockId: string, at: Placement) => void;
  addBlock: (viz: string) => void;
  addSqlBlock: () => void;
  removeBlock: (blockId: string) => void;

  setCalculations: (metrics: CalculatedMetric[]) => void;
}

const EMPTY: Editor["draft"] = null;

/**
 * Editing a dashboard is editing a document.
 *
 * The draft is a plain deep copy of the spec; every mutation replaces it, and
 * saving is one PUT. There is no separate "builder model" to keep in step with
 * the runtime — the thing being edited is exactly the thing that renders, which
 * is what makes a live preview free rather than a feature.
 */
export function useEditor(spec: DashboardSpec | null, onSaved?: () => void): Editor {
  const [draft, setDraft] = useState<DashboardSpec | null>(EMPTY);
  const [baseline, setBaseline] = useState<string>("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const start = useCallback(() => {
    if (!spec) return;
    const copy = structuredClone(spec);
    setDraft(copy);
    setBaseline(JSON.stringify(copy));
    setSelectedId(copy.blocks[0]?.id ?? null);
    setError(null);
  }, [spec]);

  // A blank page. One placeholder block, because a spec must have at least one
  // and an empty canvas with nothing to select is a dead end.
  const startBlank = useCallback((id: string, title: string, model: string) => {
    const blank: DashboardSpec = {
      $schema: "../schemas/spec.schema.json",
      id,
      specVersion: 1,
      model,
      title,
      freshness: "daily",
      params: [
        { name: "as_of", type: "date", label: "As of", default: "@latest_close" },
        { name: "compare_to", type: "date", label: "Compared to", default: "@as_of - 7d" },
      ],
      blocks: [
        {
          id: "block-1",
          viz: "table.grid",
          at: { x: 0, y: 0, w: 12, h: 6 },
          title: "New block",
          sql: { sql: "SELECT 1 AS example" },
        },
      ],
    };
    setDraft(blank);
    setBaseline("");          // everything is unsaved on a blank page
    setSelectedId("block-1");
    setError(null);
  }, []);

  const cancel = useCallback(() => {
    setDraft(EMPTY);
    setSelectedId(null);
    setError(null);
  }, []);

  const mutate = useCallback((fn: (d: DashboardSpec) => void) => {
    setDraft((current) => {
      if (!current) return current;
      const next = structuredClone(current);
      fn(next);
      return next;
    });
  }, []);

  const patchBlock = useCallback(
    (blockId: string, patch: Partial<Block>) =>
      mutate((d) => {
        const i = d.blocks.findIndex((b) => b.id === blockId);
        if (i >= 0) d.blocks[i] = { ...d.blocks[i], ...patch };
      }),
    [mutate]
  );

  const setOptions = useCallback(
    (blockId: string, options: ResolvedOptions) =>
      mutate((d) => {
        const block = d.blocks.find((b) => b.id === blockId);
        if (!block) return;
        // Store only what differs from the manifest default, so a spec stays
        // small and a later change to a default reaches every dashboard.
        block.options = pruneOptions(block.viz, options);
      }),
    [mutate]
  );

  const place = useCallback(
    (blockId: string, at: Placement) =>
      mutate((d) => {
        const block = d.blocks.find((b) => b.id === blockId);
        if (!block) return;
        block.at = {
          x: Math.max(0, Math.min(11, Math.round(at.x))),
          y: Math.max(0, Math.round(at.y)),
          w: Math.max(1, Math.min(12, Math.round(at.w))),
          h: Math.max(1, Math.round(at.h)),
        };
        // The schema rejects a block that runs off the grid, so clamp here
        // rather than let the save fail.
        if (block.at.x + block.at.w > 12) block.at.x = 12 - block.at.w;
      }),
    [mutate]
  );

  const addBlock = useCallback(
    (viz: string) => {
      let created = "";
      mutate((d) => {
        const manifest = manifests[viz];
        const base = viz.split(".").pop() ?? "block";
        let n = 1;
        while (d.blocks.some((b) => b.id === `${base}-${n}`)) n += 1;
        created = `${base}-${n}`;

        const bottom = d.blocks.reduce((m, b) => Math.max(m, b.at.y + b.at.h), 0);
        const needsTwoDims = viz === "mark.matrix";

        d.blocks.push({
          id: created,
          viz,
          at: { x: 0, y: bottom, w: 6, h: 5 },
          title: manifest?.name ?? "New block",
          // A new block must render something immediately, so it starts with
          // the first metric in the spec and a dimension that is already in use.
          query: manifest?.derivesFromSource
            ? undefined
            : {
                metrics: [firstMetric(d) ?? ""],
                by: needsTwoDims ? firstDims(d, 2) : firstDims(d, 1),
                limit: 10,
              },
          source: manifest?.derivesFromSource
            ? { block: d.blocks[0]?.id ?? "", on: "select" }
            : undefined,
        });
      });
      if (created) setSelectedId(created);
    },
    [mutate]
  );

  const addSqlBlock = useCallback(() => {
    let created = "";
    mutate((d) => {
      let n = 1;
      while (d.blocks.some((b) => b.id === `sql-${n}`)) n += 1;
      created = `sql-${n}`;
      const bottom = d.blocks.reduce((m, b) => Math.max(m, b.at.y + b.at.h), 0);
      d.blocks.push({
        id: created,
        viz: "table.grid",
        at: { x: 0, y: bottom, w: 12, h: 6 },
        title: "SQL block",
        sql: { sql: "SELECT 1 AS example" },
      });
    });
    if (created) setSelectedId(created);
  }, [mutate]);

  const removeBlock = useCallback(
    (blockId: string) =>
      mutate((d) => {
        d.blocks = d.blocks.filter((b) => b.id !== blockId);
        // A block sourcing from a deleted block would fail validation on save.
        for (const b of d.blocks) {
          if (b.source?.block === blockId) b.source = undefined;
        }
      }),
    [mutate]
  );

  const setCalculations = useCallback(
    (metrics: CalculatedMetric[]) => mutate((d) => { d.metrics = metrics; }),
    [mutate]
  );

  const save = useCallback(async () => {
    if (!draft) return;
    setSaving(true);
    setError(null);
    try {
      await api.saveSpec(draft);
      setBaseline(JSON.stringify(draft));
      onSaved?.();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }, [draft, onSaved]);

  const dirty = useMemo(
    () => Boolean(draft) && JSON.stringify(draft) !== baseline,
    [draft, baseline]
  );

  return {
    editing: draft !== null,
    draft,
    dirty,
    selectedId,
    saving,
    error,
    start,
    startBlank,
    cancel,
    save,
    select: setSelectedId,
    patchBlock,
    setOptions,
    place,
    addBlock,
    addSqlBlock,
    removeBlock,
    setCalculations,
  };
}

function firstMetric(spec: DashboardSpec): string | undefined {
  for (const b of spec.blocks) {
    if (b.query?.metrics?.length) return b.query.metrics[0];
  }
  return undefined;
}

function firstDims(spec: DashboardSpec, count: number): string[] {
  const seen: string[] = [];
  for (const b of spec.blocks) {
    for (const d of b.query?.by ?? []) {
      if (!seen.includes(d) && !d.endsWith("_date")) seen.push(d);
      if (seen.length >= count) return seen;
    }
  }
  return seen;
}
