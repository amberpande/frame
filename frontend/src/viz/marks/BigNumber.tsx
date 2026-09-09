import DeltaChip from "../../primitives/DeltaChip";
import { formatDate, formatValue } from "../../runtime/format";
import { Table } from "../../runtime/table";
import type { VizProps } from "../registry";

/** One figure. Absolute change leads, percentage follows. */
export default function BigNumber({ block, table, meta }: VizProps) {
  if (!table) return null;

  const groups = table.groups();
  const group = groups[0];
  if (!group) return <p className="vd-empty">No value.</p>;

  const xName = block.encode?.x ?? table.metrics[0]?.name ?? "";
  const col = table.column(xName);
  const now = Table.num(group.current, xName);
  const past = Table.num(group.compare, xName);
  const hasCompare = group.compare !== null;

  // When the query grouped by something, the figure belongs to a named thing
  // and saying which one is the difference between a fact and a mystery.
  const qualifier = table.dimensions.length ? group.label : null;

  return (
    <div className="vd-bignum">
      <div className="vd-bignum__value">{formatValue(now, col?.format)}</div>
      {qualifier && <div className="vd-bignum__qualifier">{qualifier}</div>}
      {hasCompare ? (
        <div className="vd-bignum__foot">
          <DeltaChip
            current={now}
            previous={past}
            format={col?.format}
            direction={col?.direction}
          />
          <span className="vd-bignum__since">vs {formatDate(meta?.params?.compare_to)}</span>
        </div>
      ) : (
        <div className="vd-bignum__foot">
          <span className="vd-bignum__since">as of {formatDate(meta?.params?.as_of)}</span>
        </div>
      )}
    </div>
  );
}
