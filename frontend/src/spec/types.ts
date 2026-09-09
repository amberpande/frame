/**
 * Mirrors backend/frame/spec/schema.py.
 *
 * Hand-maintained for now; generate it from the Pydantic model before the spec
 * schema changes a second time. Drift between these two definitions is the bug
 * class that eats the year.
 */

export type Freshness = "daily" | "hourly" | "near_real_time" | "live";

export interface Placement {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface FilterClause {
  field: string;
  op: "eq" | "ne" | "in" | "not_in" | "gt" | "gte" | "lt" | "lte" | "contains";
  value: unknown;
}

export interface SortSpec {
  by: string;
  dir: "asc" | "desc";
  abs?: boolean;
}

export interface QuerySpec {
  metrics: string[];
  by?: string[];
  filters?: FilterClause[];
  compare?: string | null;
  /** Only meaningful when a time dimension is in `by`. */
  windowDays?: number | null;
  limit?: number | null;
  order?: SortSpec | null;
}

export interface BlockSource {
  block: string;
  on: "select" | "hover" | "always";
}

export interface AgentBinding {
  task: string;
  grounding: string[];
}

export interface Block {
  id: string;
  viz: string;
  at: Placement;
  title?: string;
  subtitle?: string;
  query?: QuerySpec;
  encode?: Record<string, string>;
  sort?: SortSpec | null;
  source?: BlockSource | null;
  agent?: AgentBinding | null;
  options?: Record<string, unknown>;
}

export interface Param {
  name: string;
  type: "date" | "dimension" | "measure" | "string" | "number" | "boolean";
  label?: string;
  default?: unknown;
  of?: string;
  multi?: boolean;
}

export interface DashboardSpec {
  id: string;
  specVersion: number;
  model: string;
  title: string;
  description?: string;
  freshness: Freshness;
  owner?: string;
  tags?: string[];
  params: Param[];
  blocks: Block[];
}

export interface SpecSummary {
  id: string;
  title: string;
  description?: string;
  model: string;
  freshness: Freshness;
  owner?: string;
  tags?: string[];
  blocks: number;
  specVersion: number;
}

/* --- query envelope ---------------------------------------------------- */

export interface ValueFormat {
  style?: "integer" | "decimal" | "currency" | "percent";
  precision?: number;
  currency?: string;
  unit?: string;
  compact?: boolean;
}

export interface ColumnMeta {
  name: string;
  role: "period" | "rank" | "dimension" | "metric";
  label: string;
  format: ValueFormat;
  direction: "higher_is_better" | "lower_is_better" | "neutral";
}

export interface QueryMeta {
  planHash: string;
  queryTag: string;
  tier: string;
  cached: boolean;
  elapsedMs: number;
  rowCount: number;
  modelFingerprint: string;
  policyFingerprint: string;
  cost: {
    periods: number;
    baselineDays: number;
    dayPartitions: number;
    class: string;
    rowCap: number;
  };
  params: Record<string, unknown>;
  sql?: string;
  bindings?: Record<string, unknown>;
}

export interface QueryEnvelope {
  columns: ColumnMeta[];
  rows: unknown[][];
  meta: QueryMeta;
}

/* --- semantic model (what the builder and the agent both read) --------- */

export interface ModelMetric {
  name: string;
  label: string;
  kind: "measure" | "derived";
  format: ValueFormat;
  direction: string;
  costClass: string;
  owner: string;
  synonyms: string[];
  note?: string;
  grain: string[];
  hasBaseline: boolean;
}

export interface ModelDimension {
  name: string;
  label: string;
  kind: string;
  synonyms: string[];
  description?: string;
}

export interface SemanticModel {
  name: string;
  label?: string;
  description?: string;
  fingerprint: string;
  dimensions: ModelDimension[];
  metrics: ModelMetric[];
}
