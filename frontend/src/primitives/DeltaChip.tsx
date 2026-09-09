import type { ValueFormat } from "../spec/types";
import { formatDelta, formatPercentDelta, toneOf } from "../runtime/format";

interface Props {
  current: number;
  previous: number;
  format?: ValueFormat;
  direction?: string;
  /** Percentage is secondary and can be dropped in tight spaces. */
  showPercent?: boolean;
}

/**
 * Absolute change leads; percentage follows, smaller and quieter.
 *
 * On counts a percentage alone lies — 2 to 4 is "+100%" — so the absolute
 * figure is never the thing that gets dropped.
 */
export default function DeltaChip({
  current,
  previous,
  format,
  direction = "neutral",
  showPercent = true,
}: Props) {
  const delta = current - previous;
  const tone = toneOf(delta, direction);
  const pct = formatPercentDelta(current, previous);

  return (
    <span className={`vd-delta vd-delta--${tone}`}>
      <span className="vd-delta__abs">{formatDelta(delta, format)}</span>
      {showPercent && pct && <span className="vd-delta__pct">{pct}</span>}
    </span>
  );
}
