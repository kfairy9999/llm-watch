import { callsQueryFilters, demoAssetPath, filterCalls, type CallSearch } from "@/lib/staticDemo";
import type {
  CallDetail,
  CallPage,
  CallSummary,
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

const demoStatic = import.meta.env.VITE_DEMO_STATIC === "1";

let ledgerPromise: Promise<{ calls: CallSummary[]; search: CallSearch }> | null = null;

function loadLedger(): Promise<{ calls: CallSummary[]; search: CallSearch }> {
  if (!ledgerPromise) {
    ledgerPromise = Promise.all([readJson<CallPage>("/demo/calls.json"), readJson<CallSearch>("/demo/calls-search.json")])
      .then(([page, search]) => ({ calls: page.calls, search }))
      .catch((error: unknown) => {
        ledgerPromise = null;
        throw error;
      });
  }
  return ledgerPromise;
}

async function readJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  const body = await response.text();
  if (!response.ok) {
    throw new ApiError(response.status, `${response.status} ${response.statusText}`);
  }
  // Workers and Pages serve index.html for unknown paths. That is not a call.
  if (body.trimStart().startsWith("<")) {
    throw new ApiError(404, "404 Not Found");
  }
  try {
    return JSON.parse(body) as T;
  } catch {
    throw new ApiError(404, "404 Not Found");
  }
}

async function getDemoJson<T>(path: string): Promise<T> {
  const filters = callsQueryFilters(path);
  if (filters) {
    const ledger = await loadLedger();
    return filterCalls(ledger.calls, ledger.search, filters) as T;
  }
  const asset = demoAssetPath(path);
  if (!asset) throw new ApiError(404, "404 Not Found");
  return readJson<T>(asset);
}

export async function getJson<T>(path: string): Promise<T> {
  if (demoStatic) return getDemoJson<T>(path);
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
