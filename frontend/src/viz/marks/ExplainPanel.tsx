import { useEffect, useState } from "react";
import { api } from "../../runtime/client";
import { formatDate, formatDelta, formatPercentDelta, formatValue } from "../../runtime/format";
import { Table } from "../../runtime/table";
import type { SemanticModel } from "../../spec/types";
import { bool } from "../options";
import type { VizProps } from "../registry";

/**
 * The explain panel.
 *
 * What it shows today is the *grounding*: the exact figures, the governed
 * definitions behind them, and the compiled SQL that produced them. That is
 * precisely the payload the planner receives in Phase 3, which is why it is
 * worth rendering now — if the grounding is not legible to a person, it is not
 * going to be legible to a model either.
 *
 * The panel never queries the warehouse itself. It reads the source block's
 * result and nothing else.
 */
export default function ExplainPanel({
  block, spec, incoming, sourceTable, sourceMeta, options,
}: VizProps) {
  const [model, setModel] = useState<SemanticModel | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .model(spec.model)
      .then((m) => !cancelled && setModel(m))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [spec.model]);

  const sourceBlock = spec.blocks.find((b) => b.id === block.source?.block);
  const group = incoming?.group ?? null;
  const grounding = block.agent?.grounding ?? [];

  if (!group) {
    return (
      <div className="vd-explain">
        <p className="vd-explain__prompt">
          Select a row in <strong>{sourceBlock?.title ?? "the linked block"}</strong> to
          explain it.
        </p>
        <dl className="vd-explain__grounding">
          <dt>Grounded on</dt>
          <dd>{grounding.join(", ") || "nothing declared"}</dd>
          <dt>Task</dt>
          <dd>{block.agent?.task ?? "—"}</dd>
        </dl>
      </div>
    );
  }

  const metrics = sourceTable?.metrics ?? [];
  const primary = metrics.find((m) => !m.name.startsWith("severity."));
  const severity = metrics.find((m) => m.name.startsWith("severity."));

  const now = primary ? Table.num(group.current, primary.name) : 0;
  const past = primary ? Table.num(group.compare, primary.name) : 0;
  const z = severity ? Table.num(group.current, severity.name) : NaN;
  const pct = formatPercentDelta(now, past);

  const definitionsFor = metrics
    .map((m) => model?.metrics.find((d) => d.name === m.name))
    .filter((d): d is NonNullable<typeof d> => Boolean(d));

  return (
    <div className="vd-explain">
      <h4 className="vd-explain__subject">{group.label}</h4>

      <ul className="vd-explain__facts">
        {primary && (
          <li>
            <span>{primary.label}</span>
            <strong>
              {formatValue(past, primary.format)} → {formatValue(now, primary.format)}
            </strong>
          </li>
        )}
        {primary && (
          <li>
            <span>Change</span>
            <strong>
              {formatDelta(now - past, primary.format)}
              {pct && <span className="vd-explain__muted"> ({pct})</span>}
            </strong>
          </li>
        )}
        {Number.isFinite(z) && (
          <li>
            <span>Deviation from normal</span>
            <strong>
              {z >= 0 ? "+" : "−"}
              {Math.abs(z).toFixed(2)}σ
            </strong>
          </li>
        )}
        <li>
          <span>Window</span>
          <strong>
            {formatDate(sourceMeta?.params?.compare_to)} → {formatDate(sourceMeta?.params?.as_of)}
          </strong>
        </li>
      </ul>

      {definitionsFor.length > 0 && bool(options, "showDefinitions", true) && (
        <section className="vd-explain__section">
          <h5>Definitions</h5>
          {definitionsFor.map((d) => (
            <div key={d.name} className="vd-explain__def">
              <code>{d.name}</code>
              <p>{d.note ?? d.label}</p>
              <span className="vd-explain__owner">owned by {d.owner}</span>
            </div>
          ))}
        </section>
      )}

      {grounding.includes("query.sql") && bool(options, "showSql", true) && sourceMeta?.sql && (
        <details className="vd-explain__section">
          <summary>Compiled SQL</summary>
          <pre className="vd-explain__sql">{sourceMeta.sql}</pre>
        </details>
      )}

      <div className="vd-explain__agent">
        <button type="button" className="vd-btn" disabled>
          Explain with the model
        </button>
        <p className="vd-explain__note">
          The planner is Phase 3. Everything above is the payload it receives —
          figures, governed definitions and the exact SQL. It will never be given
          a SQL tool of its own.
        </p>
      </div>
    </div>
  );
}
