import { useEffect, useState } from "react";
import ParamBar from "./runtime/ParamBar";
import SpecRenderer from "./runtime/SpecRenderer";
import { api, getIdentity, setIdentity } from "./runtime/client";
import { SelectionProvider } from "./runtime/selection";
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
  }, [specId, identity]);

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

        {spec && (
          <main className="vd-main">
            <div className="vd-pagehead">
              <div>
                <h1>{spec.title}</h1>
                {spec.description && <p className="vd-pagehead__sub">{spec.description}</p>}
              </div>
              <dl className="vd-specmeta">
                <div>
                  <dt>spec</dt>
                  <dd>
                    {spec.id} · v{spec.specVersion}
                  </dd>
                </div>
                <div>
                  <dt>model</dt>
                  <dd>{spec.model}</dd>
                </div>
                <div>
                  <dt>freshness</dt>
                  <dd>{spec.freshness}</dd>
                </div>
              </dl>
            </div>

            <ParamBar spec={spec} params={params} resolved={resolved} onChange={setParams} />

            <SpecRenderer spec={spec} params={params} onResolved={setResolved} />

            <footer className="vd-foot">
              <p>
                Every block above was drawn from{" "}
                <code>backend/specs/{spec.id}.json</code> — a row, not a repository.
                Nothing here is specific to this dashboard.
              </p>
            </footer>
          </main>
        )}
      </div>
    </SelectionProvider>
  );
}
