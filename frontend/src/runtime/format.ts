import type { ValueFormat } from "../spec/types";

const COMPACT = new Intl.NumberFormat("en-US", {
  notation: "compact",
  maximumFractionDigits: 1,
});

export function formatValue(value: unknown, fmt: ValueFormat = {}): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(n)) return String(value);

  const precision = fmt.precision ?? (fmt.style === "integer" ? 0 : 2);

  switch (fmt.style) {
    case "currency": {
      const body = fmt.compact
        ? COMPACT.format(n)
        : n.toLocaleString("en-US", {
            minimumFractionDigits: precision,
            maximumFractionDigits: precision,
          });
      const symbol = fmt.currency === "USD" ? "$" : `${fmt.currency ?? ""} `;
      return `${symbol}${body}`;
    }
    case "percent":
      return `${(n * 100).toLocaleString("en-US", {
        minimumFractionDigits: precision,
        maximumFractionDigits: precision,
      })}%`;
    case "decimal":
      return (
        n.toLocaleString("en-US", {
          minimumFractionDigits: precision,
          maximumFractionDigits: precision,
        }) + (fmt.unit ? ` ${fmt.unit}` : "")
      );
    case "integer":
    default:
      return (
        (fmt.compact ? COMPACT.format(n) : Math.round(n).toLocaleString("en-US")) +
        (fmt.unit ? ` ${fmt.unit}` : "")
      );
  }
}

/** Absolute change leads. On counts a percentage alone lies: 2 → 4 is "+100%". */
export function formatDelta(delta: number, fmt: ValueFormat = {}): string {
  const sign = delta > 0 ? "+" : delta < 0 ? "−" : "±";
  return sign + formatValue(Math.abs(delta), fmt);
}

export function formatPercentDelta(current: number, previous: number): string | null {
  if (!previous) return null;
  const pct = ((current - previous) / Math.abs(previous)) * 100;
  const sign = pct > 0 ? "+" : pct < 0 ? "−" : "±";
  return `${sign}${Math.abs(pct).toFixed(Math.abs(pct) < 10 ? 1 : 0)}%`;
}

export function formatDate(value: unknown): string {
  if (typeof value !== "string") return String(value ?? "—");
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

/** Severity is signed: direction decides whether a move is good or bad. */
export function toneOf(
  delta: number,
  direction: string
): "good" | "bad" | "flat" {
  if (delta === 0) return "flat";
  if (direction === "neutral") return "flat";
  const worse = direction === "lower_is_better" ? delta > 0 : delta < 0;
  return worse ? "bad" : "good";
}
