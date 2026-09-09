import DeltaChip from "../../primitives/DeltaChip";
import { formatDate, formatValue } from "../../runtime/format";
import { Table } from "../../runtime/table";
import type { VizProps } from "../registry";

/** Ranked magnitude. When a comparison exists, the previous period is a quiet
 *  outline behind the bar rather than a second competing bar. */
export default function BarMark({ block, table, meta, selected, onSelect }: VizProps) {
  if (!table) return null;

  const groups = table.groups();
  if (!groups.length) return <p className="vd-empty">No rows for this selection.</p>;

  const xName = block.encode?.x ?? table.metrics[0]?.name ?? "";
  const xCol = table.column(xName);
  const hasCompare = table.hasCompare;

  const max = Math.max(
    ...groups.flatMap((g) => [Table.num(g.current, xName), Table.num(g.compare, xName)]),
    1
  );

  return (
    <div className="vd-bars">
      {hasCompare && (
        <div className="vd-legend">
          <span className="vd-legend__item">
            <i className="vd-swatch vd-swatch--past" /> {formatDate(meta?.params?.compare_to)}
          </span>
          <span className="vd-legend__item">
            <i className="vd-swatch vd-swatch--now" /> {formatDate(meta?.params?.as_of)}
          </span>
        </div>
      )}
      <ol className="vd-bars__rows">
        {groups.map((g) => {
          const now = Table.num(g.current, xName);
          const past = Table.num(g.compare, xName);
          const isSelected = selected?.key === g.key;
          return (
            <li key={g.key}>
              <button
                type="button"
                className={`vd-bars__row${isSelected ? " is-selected" : ""}`}
                onClick={() => onSelect(g)}
                aria-pressed={isSelected}
              >
                <span className="vd-bars__label" title={g.label}>
                  {g.label}
                </span>
                <span className="vd-bars__track">
                  {hasCompare && (
                    <span
                      className="vd-bars__ghost"
                      style={{ width: `${(past / max) * 100}%` }}
                    />
                  )}
                  <span className="vd-bars__fill" style={{ width: `${(now / max) * 100}%` }} />
                </span>
                <span className="vd-bars__value">{formatValue(now, xCol?.format)}</span>
                {hasCompare && (
                  <span className="vd-bars__delta">
                    <DeltaChip
                      current={now}
                      previous={past}
                      format={xCol?.format}
                      direction={xCol?.direction}
                      showPercent={false}
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
