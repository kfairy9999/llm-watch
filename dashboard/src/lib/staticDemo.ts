import type { CallPage, CallSummary } from "@/types";

/**
 * Client-side calls query for the static demo.
 * Keep this aligned with ``llmwatch.demo_export.filter_calls`` and
 * ``Store.list_calls``: exact model and status, inclusive timestamp bounds,
 * and a case-insensitive literal substring over the stored prompt JSON,
 * response text, and model. ``%`` and ``_`` are not wildcards.
 */

export type CallSearch = Record<string, { prompt_json: string; response_text: string }>;

export type CallFilters = {
  model?: string;
  status?: string;
  q?: string;
  since?: string;
  until?: string;
  limit: number;
  offset: number;
};

const STATIC_FILES: Record<string, string> = {
  "/api/meta": "/demo/meta.json",
  "/api/models": "/demo/models.json",
  "/api/metrics/summary": "/demo/metrics/summary.json",
  "/api/metrics/timeseries": "/demo/metrics/timeseries.json",
  "/api/evals/comparisons": "/demo/evals/comparisons.json",
};

export function demoAssetPath(path: string): string | null {
  const pathname = new URL(path, "http://demo.local").pathname;
  const known = STATIC_FILES[pathname];
  if (known) return known;
  const call = pathname.match(/^\/api\/calls\/([^/]+)$/);
  if (call?.[1]) return `/demo/calls/${encodeURIComponent(call[1])}.json`;
  const comparison = pathname.match(/^\/api\/evals\/comparisons\/([^/]+)$/);
  if (comparison?.[1]) return `/demo/evals/comparisons/${encodeURIComponent(comparison[1])}.json`;
  return null;
}

export function callsQueryFilters(path: string): CallFilters | null {
  const url = new URL(path, "http://demo.local");
  if (url.pathname !== "/api/calls") return null;
  return {
    model: url.searchParams.get("model") || undefined,
    status: url.searchParams.get("status") || undefined,
    q: url.searchParams.get("q") || undefined,
    since: url.searchParams.get("since") || undefined,
    until: url.searchParams.get("until") || undefined,
    limit: numberParam(url.searchParams.get("limit"), 25),
    offset: numberParam(url.searchParams.get("offset"), 0),
  };
}

export function filterCalls(calls: CallSummary[], search: CallSearch, filters: CallFilters): CallPage {
  const limit = clampLimit(filters.limit);
  const offset = clampOffset(filters.offset);
  const selected = calls.filter((call) => {
    if (filters.model && call.model !== filters.model) return false;
    if (filters.status && call.status !== filters.status) return false;
    if (filters.since && call.created_at < filters.since) return false;
    if (filters.until && call.created_at > filters.until) return false;
    if (filters.q) {
      const blob = search[call.id];
      const haystacks = [blob?.prompt_json ?? "", blob?.response_text ?? "", call.model];
      const folded = filters.q.toLowerCase();
      if (!haystacks.some((haystack) => haystack.toLowerCase().includes(folded))) return false;
    }
    return true;
  });
  return {
    total: selected.length,
    limit,
    offset,
    calls: selected.slice(offset, offset + limit),
  };
}

function numberParam(value: string | null, fallback: number): number {
  if (value == null || value === "") return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function clampLimit(value: number): number {
  if (!Number.isFinite(value)) return 25;
  return Math.max(1, Math.min(Math.trunc(value), 100));
}

function clampOffset(value: number): number {
  if (!Number.isFinite(value) || value < 0) return 0;
  return Math.trunc(value);
}
