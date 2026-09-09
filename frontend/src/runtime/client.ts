import type {
  DashboardSpec,
  ExpressionCheck,
  FilterClause,
  QueryEnvelope,
  SemanticModel,
  SpecSummary,
} from "../spec/types";

const BASE = "/api/v1";

/** Development stand-in for a real token. See backend frame/api/deps.py. */
let identity = "analyst";
export function setIdentity(name: string) {
  identity = name;
}
export function getIdentity() {
  return identity;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Frame-Identity": identity,
      ...(init?.headers ?? {}),
    },
  });

  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      // A refused query comes back structured so the UI can say which control
      // is at fault, rather than showing a stack trace.
      if (body?.error?.detail) detail = body.error.detail;
      else if (body?.detail) detail = typeof body.detail === "string" ? body.detail : detail;
    } catch {
      /* keep the status line */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  specs: () => request<SpecSummary[]>("/specs"),
  spec: (id: string) => request<DashboardSpec>(`/specs/${id}`),
  model: (name: string) => request<SemanticModel>(`/models/${name}`),

  dimensionValues: (model: string, dimension: string) =>
    request<string[]>(
      `/models/${model}/dimensions/${encodeURIComponent(dimension)}/values`
    ),

  /** Check a calculated-metric formula. Reads no data. */
  checkExpression: (model: string, expr: string) =>
    request<ExpressionCheck>("/expressions/validate", {
      method: "POST",
      body: JSON.stringify({ model, expr }),
    }),

  /** Publishing a dashboard is a write to a row. The API re-validates every
   *  block against the semantic model before storing it. */
  saveSpec: (spec: DashboardSpec) =>
    request<DashboardSpec>(`/specs/${spec.id}`, {
      method: "PUT",
      body: JSON.stringify(spec),
    }),

  blockData: (
    specId: string,
    blockId: string,
    params: Record<string, unknown>,
    explain = false,
    filters: FilterClause[] = []
  ) =>
    request<QueryEnvelope>(`/specs/${specId}/blocks/${blockId}/data`, {
      method: "POST",
      body: JSON.stringify({ params, explain, filters }),
    }),
};
