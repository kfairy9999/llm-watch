export function buildCallsQuery(filters: {
  model?: string;
  status?: string;
  q?: string;
  limit: number;
  offset: number;
}): string {
  const params = new URLSearchParams();
  if (filters.model) params.set("model", filters.model);
  if (filters.status) params.set("status", filters.status);
  if (filters.q) params.set("q", filters.q);
  params.set("limit", String(filters.limit));
  params.set("offset", String(filters.offset));
  return `/api/calls?${params.toString()}`;
}
