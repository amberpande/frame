import DeltaChip from "../../primitives/DeltaChip";
import SeverityChip from "../../primitives/SeverityChip";
import { formatDate, formatValue } from "../../runtime/format";
import { Table } from "../../runtime/table";
import type { VizProps } from "../registry";

/**
 * The signature mark.
 *
 * Two observations are not a trend: with exactly two dates a sparkline invents
 * data nobody measured. A dumbbell states only what was measured, and the
 * connector length *is* the variance — so the connector is never scaled
 * independently of the dots.
 */
export default function Dumbbell({ block, table, meta, selected, onSelect }: VizProps) {
  if (!table) return null;

  const groups = table.groups();
  if (!groups.length) return <p className="vd-empty">No rows for this selection.</p>;

  const xName = block.encode?.x ?? table.metrics[0]?.name ?? "";
  const xCol = table.column(xName);
  const sevCol = table.metrics.find((c) => c.name.startsWith("severity."));

  const values = groups.flatMap((g) => [
    Table.num(g.current, xName),
    Table.num(g.compare, xName),
  ]);
  const max = Math.max(...values, 1);
  const pct = (v: number) => (v / max) * 100;

  const asOf = formatDate(meta?.params?.as_of);
  const comparedTo = formatDate(meta?.params?.compare_to);

  return (
    <div className="vd-dumbbell">
      <div className="vd-legend">
        <span className="vd-legend__item">
          <i className="vd-dot vd-dot--past" /> {comparedTo}
        </span>
        <span className="vd-legend__item">
          <i className="vd-dot vd-dot--now" /> {asOf}
        </span>
      </div>

      <ol className="vd-dumbbell__rows">
        {groups.map((g) => {
          const now = Table.num(g.current, xName);
          const past = Table.num(g.compare, xName);
          const lo = Math.min(pct(now), pct(past));
          const hi = Math.max(pct(now), pct(past));
          const isSelected = selected?.key === g.key;

          return (
            <li key={g.key}>
              <button
                type="button"
                className={`vd-dumbbell__row${isSelected ? " is-selected" : ""}`}
                onClick={() => onSelect(g)}
                aria-pressed={isSelected}
              >
                <span className="vd-dumbbell__label" title={g.label}>
                  {g.label}
                </span>

                <span className="vd-track">
                  <span
                    className="vd-track__connector"
                    style={{ left: `${lo}%`, width: `${Math.max(hi - lo, 0)}%` }}
                  />
                  <span className="vd-dot vd-dot--past" style={{ left: `${pct(past)}%` }} />
                  <span className="vd-dot vd-dot--now" style={{ left: `${pct(now)}%` }} />
                </span>

                <span className="vd-dumbbell__value">
                  {formatValue(now, xCol?.format)}
                </span>
                <span className="vd-dumbbell__delta">
                  <DeltaChip
                    current={now}
                    previous={past}
                    format={xCol?.format}
                    direction={xCol?.direction}
                  />
                </span>
                {sevCol && (
                  <span className="vd-dumbbell__sev">
                    <SeverityChip
                      z={Table.num(g.current, sevCol.name)}
                      direction={xCol?.direction ?? "lower_is_better"}
                    />
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
