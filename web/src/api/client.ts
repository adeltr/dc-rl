import type {
  BaseResponse, CompareResponse, JobEvent, Meta, SavedScenario, Scenario, ScenarioResult, SensitivityResult,
} from "./types";

const ROOT = "/api";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(ROOT + path, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail
        : Array.isArray(body.detail) ? body.detail.map((d: { msg?: string }) => d.msg ?? "").filter(Boolean).join(" ; ")
        : JSON.stringify(body.detail);
    } catch {
      /* corps non JSON */
    }
    throw new ApiError(response.status, detail);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

const post = <T>(path: string, body: unknown) => request<T>(path, { method: "POST", body: JSON.stringify(body) });

export interface JobRef { job_id: string; result_id: string; events: string }

export const api = {
  meta: () => request<Meta>("/meta"),
  base: () => request<BaseResponse>("/scenario/base"),
  preview: (scenario: Scenario) => post<ScenarioResult>("/preview", { scenario }),
  simulate: (scenario: Scenario, clientId: string) => post<JobRef>("/simulate", { scenario, client_id: clientId }),
  result: <T = ScenarioResult>(id: string) => request<T>(`/results/${id}`),
  scenarios: () => request<SavedScenario[]>("/scenarios"),
  saveScenario: (name: string, scenario: Scenario, resultId: string | null) =>
    post<SavedScenario>("/scenarios", { name, scenario, result_id: resultId }),
  patchScenario: (id: string, patch: Partial<Pick<SavedScenario, "name" | "scenario" | "result_id">>) =>
    request<SavedScenario>(`/scenarios/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  deleteScenario: (id: string) => request<void>(`/scenarios/${id}`, { method: "DELETE" }),
  compare: (ids: string[]) => request<CompareResponse>(`/compare?ids=${ids.map(encodeURIComponent).join(",")}`),
  sensitivity: (body: { scenario: Scenario; method: "exact" | "surrogate"; pct: number; client_id: string }) =>
    post<JobRef>("/sensitivity", body),
  exportUrl: (id: string) => `${ROOT}/export/${id}.xlsx`,
  uploadWeather: async (file: File) => {
    const response = await fetch(`${ROOT}/data/weather/${encodeURIComponent(file.name.replace(/[^A-Za-z0-9_.-]/g, "_"))}`,
                                 { method: "PUT", body: await file.arrayBuffer() });
    const body = await response.json();
    if (!response.ok) throw new ApiError(response.status, body.detail);
    return body as { weather_file: string };
  },
  uploadPrice: async (file: File) => {
    const response = await fetch(`${ROOT}/data/price/${encodeURIComponent(file.name.replace(/[^A-Za-z0-9_.-]/g, "_"))}`,
                                 { method: "PUT", body: await file.arrayBuffer() });
    const body = await response.json();
    if (!response.ok) throw new ApiError(response.status, body.detail);
    return body as { csv_file: string; hours: number; min: number; max: number; mean: number };
  },
};

export type { SensitivityResult };

/** Suit une tâche en SSE ; renvoie une fonction d'arrêt. */
export function followJob(jobId: string, onEvent: (event: JobEvent) => void): () => void {
  const source = new EventSource(`${ROOT}/simulate/${jobId}/events`);
  const handler = (message: MessageEvent) => {
    const event: JobEvent = JSON.parse(message.data);
    onEvent(event);
    if (event.status === "done" || event.status === "error" || event.status === "cancelled") source.close();
  };
  for (const type of ["queued", "running", "done", "error", "cancelled"]) source.addEventListener(type, handler);
  return () => source.close();
}
