import { useEffect, useState } from "react";
import ParamBar from "./runtime/ParamBar";
import SpecRenderer from "./runtime/SpecRenderer";
import { api, getIdentity, setIdentity } from "./runtime/client";
import { SelectionProvider } from "./runtime/selection";
import Inspector from "./builder/Inspector";
import { useEditor } from "./builder/useEditor";
import type { DashboardSpec, SpecSummary } from "./spec/types";

const IDENTITIES = [
  { id: "analyst", label: "Analyst", note: "all regions, all metrics" },
  { id: "emea", label: "EMEA analyst", note: "row policy: region = EMEA" },
  { id: "restricted", label: "Contractor", note: "EMEA, and two metrics only" },
];

export default function App() {
  const [specs, setSpecs] = useState<SpecSummary[]>([]);
  const [specId, setSpecId] = useState<string | null>(null);
  const [spec, setSpec] = useState<DashboardSpec | null>(null);
  const [params, setParams] = useState<Record<string, unknown>>({});
  const [resolved, setResolved] = useState<Record<string, unknown>>({});
  const [identity, setIdentityState] = useState(getIdentity());
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  // What is edited is exactly what renders: the draft replaces the spec
  // in the tree, so the preview is the real runtime, not an approximation.
  const editor = useEditor(spec, () => setReloadKey((k) => k + 1));
  const live = editor.draft ?? spec;

  useEffect(() => {
    api
      .specs()
      .then((rows) => {
        setSpecs(rows);
        setSpecId((current) => current ?? rows[0]?.id ?? null);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!specId) return;
    setSpec(null);
    setParams({});
    api
      .spec(specId)
      .then(setSpec)
      .catch((e: Error) => setError(e.message));
  }, [specId, identity, reloadKey]);

  const changeIdentity = (id: string) => {
    setIdentity(id);
    setIdentityState(id);
    setParams({});
  };

  return (
    <SelectionProvider>
      <div className="vd-app">
        <header className="vd-topbar">
          <div className="vd-topbar__brand">
            <span className="vd-logo">Frame</span>
            <span className="vd-topbar__tag">
              one runtime · {specs.length} spec{specs.length === 1 ? "" : "s"}
            </span>
          </div>

          <div className="vd-topbar__controls">
            <label className="vd-field">
              <span>Dashboard</span>
              <select
                className="vd-select"
                value={specId ?? ""}
                onChange={(e) => setSpecId(e.target.value)}
              >
                {specs.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.title}
                  </option>
                ))}
              </select>
            </label>

            {!editor.editing && (
              <>
                <button
                  type="button"
                  className="vd-btn vd-btn--ghost"
                  onClick={() => {
                    const name = window.prompt("Name the dashboard", "My dashboard");
                    if (!name) return;
                    const id = name.toLowerCase().replace(/[^a-z0-9]+/g, "-")
                      .replace(/^-|-$/g, "") || "untitled";
                    editor.startBlank(id, name, spec?.model ?? "finance_ops");
                  }}
                >
                  New
                </button>
                {spec && (
                  <button type="button" className="vd-btn vd-btn--ghost" onClick={editor.start}>
                    Edit
                  </button>
                )}
              </>
            )}

            <label className="vd-field">
              <span>Viewing as</span>
              <select
                className="vd-select"
                value={identity}
                onChange={(e) => changeIdentity(e.target.value)}
                title={IDENTITIES.find((i) => i.id === identity)?.note}
              >
                {IDENTITIES.map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </header>

        {error && <p className="vd-fatal">{error}</p>}

        {editor.editing && (
          <div className="vd-editbar">
            <span className="vd-editbar__state">
              Editing <code>{live?.id}</code>
              {editor.dirty ? " · unsaved changes" : " · no changes"}
            </span>
            {editor.error && <span className="vd-editbar__error">{editor.error}</span>}
            <div className="vd-editbar__actions">
              <button
                type="button"
                className="vd-btn vd-btn--ghost"
                onClick={() => navigator.clipboard?.writeText(JSON.stringify(live, null, 2))}
              >
                Copy JSON
              </button>
              <button type="button" className="vd-btn vd-btn--ghost" onClick={editor.cancel}>
                Discard
              </button>
              <button
                type="button"
                className="vd-btn"
                disabled={!editor.dirty || editor.saving}
                onClick={editor.save}
              >
                {editor.saving ? "Saving..." : "Save"}
              </button>
            </div>
          </div>
        )}

        {live && (
          <main className="vd-main">
            <div className="vd-pagehead">
              <div>
                <h1>{live.title}</h1>
                {live.description && <p className="vd-pagehead__sub">{live.description}</p>}
              </div>
              <dl className="vd-specmeta">
                <div>
                  <dt>spec</dt>
                  <dd>
                    {live.id} · v{live.specVersion}
                  </dd>
                </div>
                <div>
                  <dt>model</dt>
                  <dd>{live.model}</dd>
                </div>
                <div>
                  <dt>freshness</dt>
                  <dd>{live.freshness}</dd>
                </div>
              </dl>
            </div>

            <ParamBar spec={live} params={params} resolved={resolved} onChange={setParams} />

            <div className={editor.editing ? "vd-workspace" : undefined}>
              <div className="vd-workspace__canvas">
                <SpecRenderer
                  spec={live}
                  params={params}
                  onResolved={setResolved}
                  editor={editor.editing ? editor : undefined}
                />
              </div>
              {editor.editing && (
                <Inspector
                  spec={live}
                  block={live.blocks.find((b) => b.id === editor.selectedId) ?? null}
                  editor={editor}
                />
              )}
            </div>

            {!editor.editing && (
              <footer className="vd-foot">
                <p>
                  Every block above was drawn from{" "}
                  <code>backend/specs/{live.id}.json</code> — a row, not a repository.
                  Nothing here is specific to this dashboard.
                </p>
              </footer>
            )}
          </main>
        )}
      </div>
    </SelectionProvider>
  );
}
