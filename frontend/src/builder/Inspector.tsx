import { useEffect, useState } from "react";
import { api } from "../runtime/client";
import type { Block, DashboardSpec, SemanticModel } from "../spec/types";
import { catalogue } from "../viz/registry";
import { manifests, type OptionSpec } from "../viz/manifests";
import { resolveOptions, type ResolvedOptions } from "../viz/options";
import Calculations from "./Calculations";
import type { Editor } from "./useEditor";

interface Props {
  spec: DashboardSpec;
  block: Block | null;
  editor: Editor;
}

/**
 * The properties panel.
 *
 * Every control here is generated from the manifest and the semantic model —
 * there is no per-chart code in this file, and there must never be. Adding a
 * visualization adds a manifest entry and a component; this panel picks it up
 * with no change at all.
 */
export default function Inspector({ spec, block, editor }: Props) {
  const model = useModel(spec.model);

  if (!block) {
    return (
      <aside className="vd-inspector">
        <p className="vd-inspector__empty">Select a block to edit it.</p>
        <Calculations
          modelName={spec.model}
          model={model}
          calculations={spec.metrics ?? []}
          editor={editor}
        />
        <AddBlock editor={editor} />
      </aside>
    );
  }

  const manifest = manifests[block.viz];
  const options = resolveOptions(block.viz, block.options);
  const grainFor = (metric: string) => {
    const known = model?.metrics.find((m) => m.name === metric);
    if (known) return known.grain;
    // A dashboard calculation inherits the intersection of its inputs' grains.
    const calc = (spec.metrics ?? []).find((c) => c.name === metric);
    if (!calc) return [];
    const refs = [...calc.expr.matchAll(/\{([a-zA-Z0-9_.]+)/g)].map((m) => m[1]);
    const grains = refs
      .map((r) => model?.metrics.find((m) => m.name === r)?.grain)
      .filter((g): g is string[] => Boolean(g));
    if (!grains.length) return [];
    return grains.reduce((acc, g) => acc.filter((d) => g.includes(d)));
  };

  // A dimension is only offerable if every selected metric is grained on it.
  const legalDims = (model?.dimensions ?? []).filter((d) =>
    (block.query?.metrics ?? []).every((m) => grainFor(m).includes(d.name))
  );

  return (
    <aside className="vd-inspector">
      <header className="vd-inspector__head">
        <span className="vd-inspector__id">{block.id}</span>
        <button
          type="button"
          className="vd-inspector__delete"
          onClick={() => editor.removeBlock(block.id)}
        >
          Delete
        </button>
      </header>

      <Section title="Block">
        <Field label="Title">
          <input
            className="vd-input"
            value={block.title ?? ""}
            onChange={(e) => editor.patchBlock(block.id, { title: e.target.value })}
          />
        </Field>
        <Field label="Subtitle">
          <input
            className="vd-input"
            value={block.subtitle ?? ""}
            onChange={(e) => editor.patchBlock(block.id, { subtitle: e.target.value })}
          />
        </Field>
        <Field label="Visualization">
          <select
            className="vd-select"
            value={block.viz}
            onChange={(e) => editor.patchBlock(block.id, { viz: e.target.value, options: {} })}
          >
            {catalogue().map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </select>
        </Field>
        {manifest && (
          <p className="vd-inspector__help">
            {manifest.description}
            {manifest.notFor.length > 0 && (
              <>
                {" "}
                <b>Not for:</b> {manifest.notFor[0]}
              </>
            )}
          </p>
        )}
      </Section>

      <Section title="Placement">
        <div className="vd-inspector__grid4">
          {(["x", "y", "w", "h"] as const).map((k) => (
            <Field key={k} label={k.toUpperCase()}>
              <input
                type="number"
                className="vd-input"
                value={block.at[k]}
                min={k === "w" || k === "h" ? 1 : 0}
                max={k === "x" ? 11 : k === "w" ? 12 : undefined}
                onChange={(e) =>
                  editor.place(block.id, { ...block.at, [k]: Number(e.target.value) })
                }
              />
            </Field>
          ))}
        </div>
      </Section>

      {block.query && (
        <Section title="Query">
          <Field label="Metrics">
            <TokenPicker
              selected={block.query.metrics}
              available={[
                ...(model?.metrics ?? []).map((m) => ({ value: m.name, label: m.label })),
                ...(spec.metrics ?? []).map((c) => ({ value: c.name, label: `${c.label} (calc)` })),
              ]}
              onChange={(metrics) =>
                editor.patchBlock(block.id, { query: { ...block.query!, metrics } })
              }
            />
          </Field>
          <Field label="Group by">
            <TokenPicker
              selected={block.query.by ?? []}
              available={legalDims.map((d) => ({ value: d.name, label: d.label }))}
              onChange={(by) => editor.patchBlock(block.id, { query: { ...block.query!, by } })}
            />
            {model && legalDims.length === 0 && (
              <p className="vd-inspector__warn">
                No dimension is inside every selected metric's grain.
              </p>
            )}
          </Field>
          <div className="vd-inspector__grid2">
            <Field label="Limit">
              <input
                type="number"
                className="vd-input"
                min={1}
                value={block.query.limit ?? ""}
                placeholder="none"
                onChange={(e) =>
                  editor.patchBlock(block.id, {
                    query: {
                      ...block.query!,
                      limit: e.target.value ? Number(e.target.value) : null,
                    },
                  })
                }
              />
            </Field>
            <Field label="Compare">
              <select
                className="vd-select"
                value={block.query.compare ?? ""}
                onChange={(e) =>
                  editor.patchBlock(block.id, {
                    query: { ...block.query!, compare: e.target.value || null },
                  })
                }
              >
                <option value="">No comparison</option>
                {spec.params
                  .filter((p) => p.type === "date")
                  .map((p) => (
                    <option key={p.name} value={`$${p.name}`}>
                      ${p.name}
                    </option>
                  ))}
              </select>
            </Field>
          </div>
          <Field label="Sort by">
            <select
              className="vd-select"
              value={block.sort?.by ?? ""}
              onChange={(e) =>
                editor.patchBlock(block.id, {
                  sort: e.target.value
                    ? { by: e.target.value, dir: block.sort?.dir ?? "desc", abs: block.sort?.abs }
                    : null,
                })
              }
            >
              <option value="">Default</option>
              {block.query.metrics.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </Field>
          {block.sort && (
            <div className="vd-inspector__grid2">
              <Field label="Direction">
                <select
                  className="vd-select"
                  value={block.sort.dir}
                  onChange={(e) =>
                    editor.patchBlock(block.id, {
                      sort: { ...block.sort!, dir: e.target.value as "asc" | "desc" },
                    })
                  }
                >
                  <option value="desc">Descending</option>
                  <option value="asc">Ascending</option>
                </select>
              </Field>
              <Field label="Rank on magnitude">
                <Toggle
                  checked={Boolean(block.sort.abs)}
                  onChange={(abs) =>
                    editor.patchBlock(block.id, { sort: { ...block.sort!, abs } })
                  }
                />
              </Field>
            </div>
          )}
        </Section>
      )}

      {manifest && Object.keys(manifest.options).length > 0 && (
        <Section title={`${manifest.name} options`}>
          {Object.entries(manifest.options).map(([key, spec_]) => (
            <OptionControl
              key={key}
              name={key}
              spec={spec_}
              value={options[key]}
              onChange={(v) => editor.setOptions(block.id, { ...options, [key]: v })}
            />
          ))}
        </Section>
      )}

      <Calculations
        modelName={spec.model}
        model={model}
        calculations={spec.metrics ?? []}
        editor={editor}
      />

      <AddBlock editor={editor} />
    </aside>
  );
}

/* ------------------------------------------------------------------ pieces */

function OptionControl({
  name,
  spec,
  value,
  onChange,
}: {
  name: string;
  spec: OptionSpec;
  value: ResolvedOptions[string];
  onChange: (v: ResolvedOptions[string]) => void;
}) {
  return (
    <Field label={spec.label} help={spec.help}>
      {spec.type === "boolean" && (
        <Toggle checked={Boolean(value)} onChange={onChange} />
      )}
      {spec.type === "number" && (
        <div className="vd-inspector__range">
          <input
            type="range"
            min={spec.min ?? 0}
            max={spec.max ?? 100}
            step={spec.step ?? 1}
            value={Number(value)}
            onChange={(e) => onChange(Number(e.target.value))}
          />
          <span className="vd-inspector__num">{String(value)}</span>
        </div>
      )}
      {spec.type === "select" && (
        <select
          className="vd-select"
          value={String(value)}
          onChange={(e) => onChange(e.target.value)}
        >
          {spec.choices?.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </select>
      )}
      {spec.type === "string" && (
        <input
          className="vd-input"
          value={String(value)}
          onChange={(e) => onChange(e.target.value)}
          name={name}
        />
      )}
    </Field>
  );
}

function TokenPicker({
  selected,
  available,
  onChange,
}: {
  selected: string[];
  available: { value: string; label: string }[];
  onChange: (next: string[]) => void;
}) {
  return (
    <div className="vd-tokens">
      {selected.map((s) => (
        <button
          key={s}
          type="button"
          className="vd-token is-on"
          title="Remove"
          onClick={() => onChange(selected.filter((v) => v !== s))}
        >
          {s} <span aria-hidden="true">×</span>
        </button>
      ))}
      <select
        className="vd-select vd-select--add"
        value=""
        onChange={(e) => e.target.value && onChange([...selected, e.target.value])}
      >
        <option value="">+ add</option>
        {available
          .filter((a) => !selected.includes(a.value))
          .map((a) => (
            <option key={a.value} value={a.value}>
              {a.label}
            </option>
          ))}
      </select>
    </div>
  );
}

function AddBlock({ editor }: { editor: Editor }) {
  return (
    <Section title="Add a block">
      <div className="vd-inspector__add">
        {catalogue().map((m) => (
          <button
            key={m.id}
            type="button"
            className="vd-token"
            title={m.description}
            onClick={() => editor.addBlock(m.id)}
          >
            + {m.name}
          </button>
        ))}
      </div>
    </Section>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="vd-inspector__section">
      <h4>{title}</h4>
      {children}
    </section>
  );
}

function Field({
  label,
  help,
  children,
}: {
  label: string;
  help?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="vd-inspector__field">
      <span>{label}</span>
      {children}
      {help && <em className="vd-inspector__hint">{help}</em>}
    </label>
  );
}

function Toggle({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      className={`vd-toggle-sw${checked ? " is-on" : ""}`}
      onClick={() => onChange(!checked)}
    >
      <span />
    </button>
  );
}

function useModel(name: string): SemanticModel | null {
  const [model, setModel] = useState<SemanticModel | null>(null);
  useEffect(() => {
    let cancelled = false;
    api
      .model(name)
      .then((m) => !cancelled && setModel(m))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [name]);
  return model;
}
