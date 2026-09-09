import { useEffect, useState } from "react";
import { api } from "../runtime/client";
import type { CalculatedMetric, ExpressionCheck, SemanticModel } from "../spec/types";
import type { Editor } from "./useEditor";

interface Props {
  modelName: string;
  model: SemanticModel | null;
  calculations: CalculatedMetric[];
  editor: Editor;
}

/**
 * Dashboard-defined calculations.
 *
 * A calculation is an expression over metrics that already exist. It cannot
 * reference a column, a table or a join — that is checked on the server, on
 * every keystroke, by the same validator that runs at publish time. So the
 * formula box cannot be used to smuggle SQL past the semantic layer; the worst
 * a bad formula does is refuse to save.
 */
export default function Calculations({ modelName, model, calculations, editor }: Props) {
  const [draft, setDraft] = useState<CalculatedMetric | null>(null);

  const update = (next: CalculatedMetric[]) => editor.setCalculations(next);

  return (
    <section className="vd-inspector__section">
      <h4>Calculated metrics</h4>

      {calculations.length === 0 && !draft && (
        <p className="vd-inspector__hint">
          Combine metrics that already exist — a ratio, a share, a rate. For a
          new measure over a raw column, add it to the semantic model instead.
        </p>
      )}

      {calculations.map((calc) => (
        <div key={calc.name} className="vd-calc">
          <div className="vd-calc__head">
            <code>{calc.name}</code>
            <div>
              <button
                type="button"
                className="vd-calc__link"
                onClick={() => setDraft({ ...calc })}
              >
                Edit
              </button>
              <button
                type="button"
                className="vd-calc__link vd-calc__link--danger"
                onClick={() => update(calculations.filter((c) => c.name !== calc.name))}
              >
                Remove
              </button>
            </div>
          </div>
          <span className="vd-calc__expr">{calc.expr}</span>
        </div>
      ))}

      {draft ? (
        <FormulaEditor
          modelName={modelName}
          model={model}
          value={draft}
          existing={calculations}
          onCancel={() => setDraft(null)}
          onCommit={(calc) => {
            const others = calculations.filter((c) => c.name !== calc.name);
            update([...others, calc]);
            setDraft(null);
          }}
        />
      ) : (
        <button
          type="button"
          className="vd-token"
          onClick={() =>
            setDraft({ name: "calc.", label: "", expr: "", direction: "neutral" })
          }
        >
          + New calculation
        </button>
      )}
    </section>
  );
}

function FormulaEditor({
  modelName,
  model,
  value,
  existing,
  onCancel,
  onCommit,
}: {
  modelName: string;
  model: SemanticModel | null;
  value: CalculatedMetric;
  existing: CalculatedMetric[];
  onCancel: () => void;
  onCommit: (calc: CalculatedMetric) => void;
}) {
  const [calc, setCalc] = useState(value);
  const [check, setCheck] = useState<ExpressionCheck | null>(null);

  // Validated server-side as you type, by the same code that runs at publish
  // time — so what the editor accepts and what the platform accepts cannot
  // drift apart.
  useEffect(() => {
    if (!calc.expr.trim()) {
      setCheck(null);
      return;
    }
    let cancelled = false;
    const t = setTimeout(() => {
      api
        .checkExpression(modelName, calc.expr)
        .then((r) => !cancelled && setCheck(r))
        .catch(() => undefined);
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [calc.expr, modelName]);

  const nameOk = /^calc\.[a-z][a-z0-9_]*$/.test(calc.name);
  const clash =
    existing.some((c) => c.name === calc.name && c.name !== value.name) ||
    Boolean(model?.metrics.some((m) => m.name === calc.name));
  const canSave = nameOk && !clash && Boolean(calc.label.trim()) && check?.ok === true;

  const insert = (token: string) =>
    setCalc((c) => ({ ...c, expr: `${c.expr}${c.expr && !c.expr.endsWith(" ") ? " " : ""}${token}` }));

  return (
    <div className="vd-calc vd-calc--editing">
      <label className="vd-inspector__field">
        <span>Name</span>
        <input
          className="vd-input"
          value={calc.name}
          spellCheck={false}
          onChange={(e) => setCalc({ ...calc, name: e.target.value })}
        />
        {!nameOk && <em className="vd-inspector__warn">Must look like calc.exposure_per_item</em>}
        {clash && <em className="vd-inspector__warn">That name is already taken</em>}
      </label>

      <label className="vd-inspector__field">
        <span>Label</span>
        <input
          className="vd-input"
          value={calc.label}
          onChange={(e) => setCalc({ ...calc, label: e.target.value })}
        />
      </label>

      <label className="vd-inspector__field">
        <span>Formula</span>
        <textarea
          className="vd-input vd-calc__input"
          rows={3}
          spellCheck={false}
          placeholder="{exception.value_usd} / NULLIF({exception.count}, 0)"
          value={calc.expr}
          onChange={(e) => setCalc({ ...calc, expr: e.target.value })}
        />
      </label>

      <div className="vd-calc__palette">
        {model?.metrics.slice(0, 40).map((m) => (
          <button
            key={m.name}
            type="button"
            className="vd-token"
            title={m.name}
            onClick={() => insert(`{${m.name}}`)}
          >
            {m.label}
          </button>
        ))}
      </div>
      <div className="vd-calc__palette">
        {["+", "-", "*", "/", "(", ")", "NULLIF(", "ROUND(", "COALESCE("].map((op) => (
          <button key={op} type="button" className="vd-token" onClick={() => insert(op)}>
            {op}
          </button>
        ))}
      </div>

      {check && (
        <p className={check.ok ? "vd-calc__ok" : "vd-calc__error"}>
          {check.ok
            ? `Valid. Uses ${check.references?.join(", ")}. Can be grouped by ${
                check.grain?.length ?? 0
              } dimension${check.grain?.length === 1 ? "" : "s"}.`
            : check.error?.detail}
        </p>
      )}

      <div className="vd-inspector__grid2">
        <label className="vd-inspector__field">
          <span>Format</span>
          <select
            className="vd-select"
            value={String(calc.format?.style ?? "decimal")}
            onChange={(e) =>
              setCalc({
                ...calc,
                format:
                  e.target.value === "percent"
                    ? { style: "percent", precision: 1 }
                    : e.target.value === "currency"
                      ? { style: "currency", currency: "USD" }
                      : e.target.value === "integer"
                        ? { style: "integer" }
                        : { style: "decimal", precision: 2 },
              })
            }
          >
            <option value="decimal">Decimal</option>
            <option value="integer">Integer</option>
            <option value="percent">Percent</option>
            <option value="currency">Currency</option>
          </select>
        </label>
        <label className="vd-inspector__field">
          <span>Better when</span>
          <select
            className="vd-select"
            value={calc.direction ?? "neutral"}
            onChange={(e) =>
              setCalc({ ...calc, direction: e.target.value as CalculatedMetric["direction"] })
            }
          >
            <option value="neutral">Neutral</option>
            <option value="lower_is_better">Lower</option>
            <option value="higher_is_better">Higher</option>
          </select>
        </label>
      </div>

      <div className="vd-calc__actions">
        <button type="button" className="vd-btn vd-btn--ghost" onClick={onCancel}>
          Cancel
        </button>
        <button
          type="button"
          className="vd-btn"
          disabled={!canSave}
          onClick={() => onCommit(calc)}
        >
          Add
        </button>
      </div>
    </div>
  );
}
