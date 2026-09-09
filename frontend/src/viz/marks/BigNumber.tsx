import DeltaChip from "../../primitives/DeltaChip";
import { formatDate, formatValue } from "../../runtime/format";
import { Table } from "../../runtime/table";
import { bool, str } from "../options";
import type { VizProps } from "../registry";

/** One figure. Absolute change leads, percentage follows. */
export default function BigNumber({ block, table, meta, options }: VizProps) {
  if (!table) return null;

  const groups = table.groups();
  const group = groups[0];
  if (!group) return <p className="vd-empty">No value.</p>;

  const size = str(options, "size", "large");
  const showDelta = bool(options, "showDelta", true);
  const showPercent = bool(options, "showPercent", true);
  const neutral = str(options, "goodDirection", "metric") === "none";

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
      <div className={`vd-bignum__value vd-bignum__value--${size}`}>
        {formatValue(now, col?.format)}
      </div>
      {qualifier && <div className="vd-bignum__qualifier">{qualifier}</div>}
      {hasCompare && showDelta ? (
        <div className="vd-bignum__foot">
          <DeltaChip
            current={now}
            previous={past}
            format={col?.format}
            direction={neutral ? "neutral" : col?.direction}
            showPercent={showPercent}
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
