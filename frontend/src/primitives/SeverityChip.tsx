interface Props {
  z: number;
  /** Below this, a move is inside normal and gets no emphasis at all. */
  threshold?: number;
  direction?: string;
}

/**
 * Severity is signed.
 *
 * A large move in the good direction is just as far outside normal and ranks
 * the same, but it is never styled as a warning. Magnitude sets the weight;
 * sign and the metric's direction set the colour.
 */
export default function SeverityChip({ z, threshold = 2, direction = "lower_is_better" }: Props) {
  if (!Number.isFinite(z)) return <span className="vd-sev vd-sev--none">—</span>;

  const magnitude = Math.abs(z);
  if (magnitude < threshold) {
    return (
      <span className="vd-sev vd-sev--normal" title="Inside its own normal movement">
        {z >= 0 ? "+" : "−"}
        {magnitude.toFixed(2)}σ
      </span>
    );
  }

  const worse = direction === "lower_is_better" ? z > 0 : z < 0;
  const tone = direction === "neutral" ? "notable" : worse ? "bad" : "good";

  return (
    <span
      className={`vd-sev vd-sev--${tone}`}
      title={
        worse
          ? `${magnitude.toFixed(2)} standard deviations outside normal, in the wrong direction`
          : `${magnitude.toFixed(2)} standard deviations outside normal, in the right direction`
      }
    >
      {z >= 0 ? "+" : "−"}
      {magnitude.toFixed(2)}σ
    </span>
  );
}
