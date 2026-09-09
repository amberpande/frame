import { manifests, type OptionSpec } from "./manifests";

export type OptionValue = boolean | number | string;
export type ResolvedOptions = Record<string, OptionValue>;

/**
 * A block's options, merged over the manifest's declared defaults.
 *
 * A spec only stores what was actually changed, so a block with no `options`
 * key still renders exactly as the mark's author intended, and adding a new
 * option later does not require touching a single existing spec.
 */
export function resolveOptions(
  vizId: string,
  stored: Record<string, unknown> | undefined
): ResolvedOptions {
  const declared = manifests[vizId]?.options ?? {};
  const out: ResolvedOptions = {};

  for (const [key, spec] of Object.entries(declared)) {
    out[key] = spec.default;
  }
  if (!stored) return out;

  for (const [key, value] of Object.entries(stored)) {
    const spec = declared[key];
    // An undeclared or wrongly-typed option is ignored rather than trusted:
    // specs are editable data and may be older than the mark.
    if (!spec) continue;
    const coerced = coerce(value, spec);
    if (coerced !== undefined) out[key] = coerced;
  }
  return out;
}

function coerce(value: unknown, spec: OptionSpec): OptionValue | undefined {
  switch (spec.type) {
    case "boolean":
      return typeof value === "boolean" ? value : undefined;
    case "number": {
      const n = typeof value === "number" ? value : Number(value);
      if (!Number.isFinite(n)) return undefined;
      const lo = spec.min ?? -Infinity;
      const hi = spec.max ?? Infinity;
      return Math.min(Math.max(n, lo), hi);
    }
    case "select":
      return spec.choices?.some((c) => c.value === value) ? (value as string) : undefined;
    case "string":
      return typeof value === "string" ? value : undefined;
  }
}

/** Only what differs from the default is worth storing in a spec. */
export function pruneOptions(vizId: string, values: ResolvedOptions): Record<string, OptionValue> {
  const declared = manifests[vizId]?.options ?? {};
  const out: Record<string, OptionValue> = {};
  for (const [key, value] of Object.entries(values)) {
    if (declared[key] && declared[key].default !== value) out[key] = value;
  }
  return out;
}

export const bool = (o: ResolvedOptions, k: string, fallback = false): boolean =>
  typeof o[k] === "boolean" ? (o[k] as boolean) : fallback;

export const num = (o: ResolvedOptions, k: string, fallback = 0): number =>
  typeof o[k] === "number" ? (o[k] as number) : fallback;

export const str = (o: ResolvedOptions, k: string, fallback = ""): string =>
  typeof o[k] === "string" ? (o[k] as string) : fallback;
