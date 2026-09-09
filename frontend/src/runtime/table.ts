import type { ColumnMeta, QueryEnvelope } from "../spec/types";

export type Record_ = Record<string, unknown>;

export interface Group {
  /** Stable key for the dimension tuple. */
  key: string;
  dims: Record<string, unknown>;
  /** Label for the leading dimension — what a mark puts on the axis. */
  label: string;
  rank: number;
  current: Record_ | null;
  compare: Record_ | null;
}

/**
 * A thin view over the query envelope.
 *
 * Marks consume `groups()`, never raw rows: a two-period result arrives as one
 * row per period, and every mark would otherwise re-implement the pairing.
 */
export class Table {
  readonly columns: ColumnMeta[];
  readonly rows: unknown[][];

  constructor(envelope: QueryEnvelope) {
    this.columns = envelope.columns;
    this.rows = envelope.rows;
  }

  column(name: string): ColumnMeta | undefined {
    return this.columns.find((c) => c.name === name);
  }

  get dimensions(): ColumnMeta[] {
    return this.columns.filter((c) => c.role === "dimension");
  }

  get metrics(): ColumnMeta[] {
    return this.columns.filter((c) => c.role === "metric");
  }

  records(): Record_[] {
    const names = this.columns.map((c) => c.name);
    return this.rows.map((row) => {
      const out: Record_ = {};
      names.forEach((n, i) => (out[n] = row[i]));
      return out;
    });
  }

  get hasCompare(): boolean {
    return this.records().some((r) => r.__period === "compare");
  }

  groups(): Group[] {
    const dims = this.dimensions;
    const map = new Map<string, Group>();

    for (const rec of this.records()) {
      const dimValues: Record<string, unknown> = {};
      for (const d of dims) dimValues[d.name] = rec[d.name];
      const key = dims.length
        ? dims.map((d) => String(rec[d.name])).join(" ∕ ")
        : "__total__";

      let group = map.get(key);
      if (!group) {
        group = {
          key,
          dims: dimValues,
          label: dims.length ? String(rec[dims[0].name]) : "Total",
          rank: Number(rec.__rank ?? 0),
          current: null,
          compare: null,
        };
        map.set(key, group);
      }
      if (rec.__period === "compare") group.compare = rec;
      else group.current = rec;
      group.rank = Math.min(group.rank || Infinity, Number(rec.__rank ?? Infinity));
    }

    return [...map.values()].sort((a, b) => a.rank - b.rank);
  }

  /** Numeric accessor that tolerates nulls without poisoning arithmetic. */
  static num(rec: Record_ | null, field: string): number {
    if (!rec) return 0;
    const v = rec[field];
    if (v === null || v === undefined) return 0;
    const n = Number(v);
    return Number.isFinite(n) ? n : 0;
  }
}
