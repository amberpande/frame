import { lazy, type ComponentType, type LazyExoticComponent } from "react";
import type { Block, DashboardSpec, QueryMeta } from "../spec/types";
import type { Group, Table } from "../runtime/table";
import type { Selection } from "../runtime/selection";
import { manifests, type VizManifest } from "./manifests";
import type { ResolvedOptions } from "./options";

export interface VizProps {
  block: Block;
  /** The block's options merged over the manifest defaults. Never undefined. */
  options: ResolvedOptions;
  spec: DashboardSpec;
  table: Table | null;
  meta: QueryMeta | null;
  /** This block's own selection. */
  selected: Group | null;
  onSelect: (group: Group | null) => void;
  /** What the block named in `source` currently has selected. */
  incoming: Selection | null;
  /** The source block's data, for blocks that derive from another. */
  sourceTable: Table | null;
  sourceMeta: QueryMeta | null;
}

export interface VizEntry {
  manifest: VizManifest;
  component: LazyExoticComponent<ComponentType<VizProps>>;
}

/**
 * Adding the thirtieth visualization costs one manifest and one component —
 * not one more screen in the builder, and not a deploy.
 */
export const registry: Record<string, VizEntry> = {
  "mark.dumbbell": {
    manifest: manifests["mark.dumbbell"],
    component: lazy(() => import("./marks/Dumbbell")),
  },
  "mark.bar": {
    manifest: manifests["mark.bar"],
    component: lazy(() => import("./marks/BarMark")),
  },
  "big.number": {
    manifest: manifests["big.number"],
    component: lazy(() => import("./marks/BigNumber")),
  },
  "briefing.band": {
    manifest: manifests["briefing.band"],
    component: lazy(() => import("./marks/BriefingBand")),
  },
  "mark.line": {
    manifest: manifests["mark.line"],
    component: lazy(() => import("./marks/LineMark")),
  },
  "mark.matrix": {
    manifest: manifests["mark.matrix"],
    component: lazy(() => import("./marks/MatrixMark")),
  },
  "table.grid": {
    manifest: manifests["table.grid"],
    component: lazy(() => import("./marks/DataTable")),
  },
  "panel.explain": {
    manifest: manifests["panel.explain"],
    component: lazy(() => import("./marks/ExplainPanel")),
  },
};

export function resolve(vizId: string): VizEntry | undefined {
  return registry[vizId];
}

export function catalogue(): VizManifest[] {
  return Object.values(registry).map((e) => e.manifest);
}
