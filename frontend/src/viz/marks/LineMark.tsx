import { formatValue } from "../../runtime/format";
import { Table } from "../../runtime/table";
import { bool, num } from "../options";
import type { VizProps } from "../registry";

interface Series {
  name: string;
  points: { x: string; y: number }[];
}

/**
 * A line over a real time dimension.
 *
 * The rule that bans a sparkline across two dates is not a ban on lines — it
 * is a ban on drawing a trend through two observations. Over seventy-six daily
 * observations a line is the honest mark, and the shape is the point.
 */
export default function LineMark({ block, table, options }: VizProps) {
  if (!table) return null;

  const dims = table.dimensions;
  if (!dims.length) return <p className="vd-empty">A line needs a time dimension.</p>;

  const xName = block.encode?.x ?? dims[0].name;
  const seriesName = block.encode?.series ?? dims[1]?.name;
  const yName = block.encode?.y ?? table.metrics[0]?.name ?? "";
  const yCol = table.column(yName);

  const records = table.records().filter((r) => r.__period !== "compare");

  const xValues = [...new Set(records.map((r) => String(r[xName])))].sort();
  const seriesMap = new Map<string, Map<string, number>>();
  for (const rec of records) {
    const key = seriesName ? String(rec[seriesName]) : (yCol?.label ?? "value");
    if (!seriesMap.has(key)) seriesMap.set(key, new Map());
    seriesMap.get(key)!.set(String(rec[xName]), Table.num(rec, yName));
  }

  const series: Series[] = [...seriesMap.entries()].map(([name, points]) => ({
    name,
    points: xValues.map((x) => ({ x, y: points.get(x) ?? 0 })),
  }));

  const showArea = bool(options, "showArea", false);
  const showEndpoint = bool(options, "showEndpoint", true);
  const strokeWidth = num(options, "strokeWidth", 1.75);
  const yFromZero = bool(options, "yFromZero", true);
  const tickCount = Math.round(num(options, "tickCount", 3));

  const allY = series.flatMap((s) => s.points.map((p) => p.y));
  const maxY = Math.max(...allY, 1);
  // Not starting at zero exaggerates small movements, so it is opt-in.
  const minY = yFromZero ? 0 : Math.min(...allY, 0);
  const W = 720;
  const H = 210;
  const PAD = { top: 12, right: 14, bottom: 26, left: 48 };
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;

  const px = (i: number) =>
    PAD.left + (xValues.length === 1 ? plotW / 2 : (i / (xValues.length - 1)) * plotW);
  const span = maxY - minY || 1;
  const py = (v: number) => PAD.top + plotH - ((v - minY) / span) * plotH;

  // Every gridline names a value the chart actually reaches.
  const ticks = Array.from({ length: tickCount }, (_, i) =>
    Math.round(minY + (span * i) / (tickCount - 1))
  );
  const strokes = ["var(--vd-mark-now)", "var(--vd-warn)", "var(--vd-bad)", "var(--vd-mark-past)"];

  const labelEvery = Math.max(1, Math.ceil(xValues.length / 8));

  return (
    <div className="vd-line">
      {series.length > 1 && (
        <div className="vd-legend">
          {series.map((s, i) => (
            <span key={s.name} className="vd-legend__item">
              <i
                className="vd-swatch"
                style={{ background: strokes[i % strokes.length] }}
              />
              {s.name}
            </span>
          ))}
        </div>
      )}

      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="vd-line__svg"
        role="img"
        aria-label={`${yCol?.label ?? "value"} over time`}
        preserveAspectRatio="none"
      >
        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={py(t)}
              y2={py(t)}
              stroke="var(--vd-rule)"
              strokeWidth="1"
            />
            <text
              x={PAD.left - 8}
              y={py(t) + 3.5}
              textAnchor="end"
              className="vd-line__tick"
            >
              {formatValue(t, yCol?.format)}
            </text>
          </g>
        ))}

        {showArea &&
          series.map((s, i) => (
            <path
              key={`${s.name}-area`}
              fill={strokes[i % strokes.length]}
              fillOpacity={series.length > 1 ? 0.1 : 0.16}
              stroke="none"
              d={
                `M ${px(0)},${py(minY)} ` +
                s.points.map((p, idx) => `L ${px(idx)},${py(p.y)}`).join(" ") +
                ` L ${px(s.points.length - 1)},${py(minY)} Z`
              }
            />
          ))}

        {series.map((s, i) => (
          <polyline
            key={s.name}
            fill="none"
            stroke={strokes[i % strokes.length]}
            strokeWidth={strokeWidth}
            strokeLinejoin="round"
            points={s.points.map((p, idx) => `${px(idx)},${py(p.y)}`).join(" ")}
          />
        ))}

        {/* Emphasise the endpoint: it is the value the reader came for. */}
        {showEndpoint &&
          series.map((s, i) => {
            const last = s.points[s.points.length - 1];
            return last ? (
              <circle
                key={`${s.name}-end`}
                cx={px(s.points.length - 1)}
                cy={py(last.y)}
                r="3"
                fill={strokes[i % strokes.length]}
              />
            ) : null;
          })}

        {xValues.map((x, i) =>
          i % labelEvery === 0 ? (
            <text
              key={x}
              x={px(i)}
              y={H - 8}
              textAnchor="middle"
              className="vd-line__tick"
            >
              {x.slice(5)}
            </text>
          ) : null
        )}
      </svg>
    </div>
  );
}
