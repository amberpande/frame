import SeverityChip from "../../primitives/SeverityChip";
import { formatValue } from "../../runtime/format";
import { Table } from "../../runtime/table";
import { bool, str } from "../options";
import type { VizProps } from "../registry";

/** Exact values. Digits line up, so tabular numerals are not optional. */
export default function DataTable({ table, selected, onSelect, options }: VizProps) {
  if (!table) return null;

  const groups = table.groups();
  if (!groups.length) return <p className="vd-empty">No rows for this selection.</p>;

  const density = str(options, "density", "regular");
  const zebra = bool(options, "zebra", false);
  const showRank = bool(options, "showRank", false);

  const dims = table.dimensions;
  const metrics = table.metrics;

  return (
    <div className="vd-tablewrap">
      <table className={`vd-table vd-table--${density}${zebra ? " vd-table--zebra" : ""}`}>
        <thead>
          <tr>
            {showRank && (
              <th scope="col" className="vd-table__num">#</th>
            )}
            {dims.map((d) => (
              <th key={d.name} scope="col">
                {d.label}
              </th>
            ))}
            {metrics.map((m) => (
              <th key={m.name} scope="col" className="vd-table__num">
                {m.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {groups.map((g) => {
            const isSelected = selected?.key === g.key;
            return (
              <tr
                key={g.key}
                className={isSelected ? "is-selected" : undefined}
                onClick={() => onSelect(g)}
              >
                {showRank && <td className="vd-table__num">{g.rank}</td>}
                {dims.map((d) => (
                  <td key={d.name}>{String(g.dims[d.name] ?? "—")}</td>
                ))}
                {metrics.map((m) => (
                  <td key={m.name} className="vd-table__num">
                    {m.name.startsWith("severity.") ? (
                      <SeverityChip z={Table.num(g.current, m.name)} />
                    ) : (
                      formatValue(g.current?.[m.name], m.format)
                    )}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
