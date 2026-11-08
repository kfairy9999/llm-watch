import type {
  CallDetail,
  CallPage,
  ComparisonCard,
  ComparisonDetail,
  Meta,
  MetricsSummary,
  Timeseries,
} from "./types";

let apiBase = "";

export function setApiBase(value: string): void {
  apiBase = value.replace(/\/$/, "");
}

export function getApiBase(): string {
  return apiBase;
}

export async function loadConfig(): Promise<void> {
  try {
    const response = await fetch("/config.json", { cache: "no-store" });
    if (!response.ok) return;
    const body = (await response.json()) as { apiBase?: unknown };
    if (typeof body.apiBase === "string") setApiBase(body.apiBase);
  } catch {
    // Same-origin /api via the Vite proxy or nginx.
  }
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${apiBase}${path}`);
  if (!response.ok) {
    throw new ApiError(response.status, `${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

export const getMeta = () => getJson<Meta>("/api/meta");
export const getSummary = () => getJson<MetricsSummary>("/api/metrics/summary");
export const getTimeseries = () => getJson<Timeseries>("/api/metrics/timeseries");
export const getCalls = (query: string) => getJson<CallPage>(query);
export const getCall = (id: string) => getJson<CallDetail>(`/api/calls/${encodeURIComponent(id)}`);
export const getModels = () => getJson<{ models: string[] }>("/api/models");
export const getComparisons = () => getJson<{ comparisons: ComparisonCard[] }>("/api/evals/comparisons");
export const getComparison = (id: string) =>
  getJson<ComparisonDetail>(`/api/evals/comparisons/${encodeURIComponent(id)}`);
