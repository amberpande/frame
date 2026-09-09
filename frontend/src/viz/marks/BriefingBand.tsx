import SeverityChip from "../../primitives/SeverityChip";
import { formatDate, formatDelta, formatValue } from "../../runtime/format";
import { Table, type Group } from "../../runtime/table";
import { bool, num } from "../options";
import type { VizProps } from "../registry";

function list(items: string[]): string {
  if (items.length <= 1) return items[0] ?? "";
  if (items.length === 2) return `${items[0]} and ${items[1]}`;
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/**
 * Lead with the answer.
 *
 * The page opens with a written summary, not a grid. Every sentence here is
 * assembled deterministically from the block's own rows — this is the
 * conclusion the data supports, not a generated guess about it.
 */
export default function BriefingBand({ block, table, meta, onSelect, options }: VizProps) {
  if (!table) return null;

  const groups = table.groups();
  if (!groups.length) return <p className="vd-empty">Nothing to report for this selection.</p>;

  const OUTSIDE_NORMAL = num(options, "threshold", 2);
  const showChips = bool(options, "showChips", true);
  const maxChips = num(options, "maxChips", 8);

  const xName = block.encode?.x ?? table.metrics[0]?.name ?? "";
  const xCol = table.column(xName);
  const sevCol = table.metrics.find((c) => c.name.startsWith("severity."));
  const dimLabel = (table.dimensions[0]?.label ?? "group").toLowerCase();
  const direction = xCol?.direction ?? "lower_is_better";

  const totalNow = groups.reduce((s, g) => s + Table.num(g.current, xName), 0);
  const totalPast = groups.reduce((s, g) => s + Table.num(g.compare, xName), 0);
  const hasCompare = table.hasCompare;

  const sev = (g: Group) => (sevCol ? Table.num(g.current, sevCol.name) : 0);
  const outside = sevCol
    ? groups.filter((g) => Math.abs(sev(g)) >= OUTSIDE_NORMAL)
    : [];
  const worse = outside.filter((g) =>
    direction === "lower_is_better" ? sev(g) > 0 : sev(g) < 0
  );
  const better = outside.filter((g) => !worse.includes(g));

  return (
    <div className="vd-briefing">
      <p className="vd-briefing__lead">
        <strong>{formatValue(totalNow, xCol?.format)}</strong> {xCol?.label.toLowerCase()}{" "}
        across {groups.length} {dimLabel}
        {groups.length === 1 ? "" : "s"}
        {hasCompare && (
          <>
            ,{" "}
            <strong>{formatDelta(totalNow - totalPast, xCol?.format)}</strong> on{" "}
            {formatDate(meta?.params?.compare_to)}
          </>
        )}
        .
      </p>

      {sevCol && (
        <p className="vd-briefing__body">
          {outside.length === 0 ? (
            <>Every {dimLabel} sits inside its own normal movement. Nothing needs attention today.</>
          ) : (
            <>
              {outside.length} of {groups.length} moved outside normal
              {worse.length > 0 && (
                <>
                  {" "}
                  — {list(worse.map((g) => g.label))}{" "}
                  {worse.length === 1 ? "is" : "are"} worse than usual
                </>
              )}
              {better.length > 0 && (
                <>
                  {worse.length > 0 ? ", while " : " — "}
                  {list(better.map((g) => g.label))}{" "}
                  {better.length === 1 ? "has" : "have"} improved
                </>
              )}
              . Ranked by deviation from the 28-day normal, not by raw size.
            </>
          )}
        </p>
      )}

      {outside.length > 0 && showChips && (
        <div className="vd-briefing__chips">
          {outside
            .slice()
            .sort((a, b) => Math.abs(sev(b)) - Math.abs(sev(a)))
            .slice(0, maxChips)
            .map((g) => (
              <button
                key={g.key}
                type="button"
                className="vd-briefing__chip"
                onClick={() => onSelect(g)}
              >
                <span className="vd-briefing__chip-label">{g.label}</span>
                <SeverityChip z={sev(g)} direction={direction} />
              </button>
            ))}
        </div>
      )}
    </div>
  );
}
