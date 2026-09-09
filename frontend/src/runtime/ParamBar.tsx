import { useEffect, useState } from "react";
import type { DashboardSpec, Param } from "../spec/types";
import { api } from "./client";

interface Props {
  spec: DashboardSpec;
  /** Overrides the user has set. */
  params: Record<string, unknown>;
  /** What the server resolved, including @latest_close and relative dates. */
  resolved: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
}

function DimensionParam({
  param,
  model,
  value,
  onChange,
}: {
  param: Param;
  model: string;
  value: string[];
  onChange: (next: string[]) => void;
}) {
  const [options, setOptions] = useState<string[]>([]);

  useEffect(() => {
    let cancelled = false;
    if (!param.of) return;
    api
      .dimensionValues(model, param.of)
      .then((vals) => !cancelled && setOptions(vals))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [model, param.of]);

  if (!options.length) return null;

  return (
    <div className="vd-param">
      <span className="vd-param__label">{param.label ?? param.name}</span>
      <div className="vd-toggles">
        {options.map((opt) => {
          const on = value.includes(opt);
          return (
            <button
              key={opt}
              type="button"
              className={`vd-toggle${on ? " is-on" : ""}`}
              aria-pressed={on}
              onClick={() =>
                onChange(on ? value.filter((v) => v !== opt) : [...value, opt])
              }
            >
              {opt}
            </button>
          );
        })}
        {value.length > 0 && (
          <button type="button" className="vd-toggle vd-toggle--clear" onClick={() => onChange([])}>
            All
          </button>
        )}
      </div>
    </div>
  );
}

/** The spec's params, rendered generically. No per-dashboard control code. */
export default function ParamBar({ spec, params, resolved, onChange }: Props) {
  const set = (name: string, value: unknown) => onChange({ ...params, [name]: value });

  return (
    <div className="vd-parambar">
      {spec.params.map((param) => {
        if (param.type === "date") {
          const current =
            (params[param.name] as string) ??
            (typeof resolved[param.name] === "string"
              ? (resolved[param.name] as string).slice(0, 10)
              : "");
          return (
            <label key={param.name} className="vd-param">
              <span className="vd-param__label">{param.label ?? param.name}</span>
              <input
                type="date"
                className="vd-input"
                value={current}
                onChange={(e) => set(param.name, e.target.value)}
              />
            </label>
          );
        }

        if (param.type === "dimension" && param.of) {
          const value = (params[param.name] as string[]) ?? [];
          return (
            <DimensionParam
              key={param.name}
              param={param}
              model={spec.model}
              value={value}
              onChange={(next) => set(param.name, next)}
            />
          );
        }

        return null;
      })}
    </div>
  );
}
