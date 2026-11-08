import type { CallSummary } from "@/types";
import { callsQueryFilters, demoAssetPath, filterCalls, type CallSearch } from "@/lib/staticDemo";

function summary(
  partial: Pick<CallSummary, "id" | "model" | "status" | "created_at"> & Partial<CallSummary>,
): CallSummary {
  return {
    endpoint: "/v1/chat/completions",
    provider: "groq",
    prompt_preview: "",
    response_preview: "",
    prompt_tokens: 1,
    completion_tokens: 1,
    total_tokens: 2,
    token_source: "simulated",
    latency_ms: 10,
    cost_usd: 0,
    price_source: "default",
    error_type: null,
    error_message: null,
    http_status: 200,
    attempts: 1,
    synthetic: true,
    data_label: "synthetic demo",
    streaming: false,
    route: "support",
    metadata: {},
    ...partial,
  };
}

const calls = [
  summary({ id: "a", model: "llama-3.1-8b-instant", status: "ok", created_at: "2026-11-01T00:00:00Z" }),
  summary({ id: "b", model: "llama-3.3-70b-versatile", status: "error", created_at: "2026-11-02T00:00:00Z" }),
  summary({ id: "c", model: "llama-3.1-8b-instant", status: "ok", created_at: "2026-11-03T00:00:00Z" }),
];

const search: CallSearch = {
  a: {
    prompt_json: '[{"role": "system", "content": "fictional company"}]',
    response_text: "Standard shipping to Austin is 5 business days.",
  },
  b: {
    prompt_json: "100% sure there is a literal_underscore",
    response_text: "",
  },
  c: {
    prompt_json: "warranty appears only after the preview window ".repeat(8),
    response_text: "short",
  },
};

describe("static demo calls filter", () => {
  it("matches model, status, time, and literal case-insensitive text", () => {
    const austin = filterCalls(calls, search, { q: "austin", limit: 25, offset: 0 });
    expect(austin.total).toBe(1);
    expect(austin.calls.map((call) => call.id)).toEqual(["a"]);

    const fictional = filterCalls(calls, search, { q: "FICTIONAL", limit: 25, offset: 0 });
    expect(fictional.calls.map((call) => call.id)).toEqual(["a"]);

    const percent = filterCalls(calls, search, { q: "%", limit: 25, offset: 0 });
    expect(percent.calls.map((call) => call.id)).toEqual(["b"]);

    const underscore = filterCalls(calls, search, { q: "_", limit: 25, offset: 0 });
    expect(underscore.calls.map((call) => call.id)).toEqual(["b"]);

    const model = filterCalls(calls, search, { model: "llama-3.1-8b-instant", status: "ok", limit: 1, offset: 1 });
    expect(model.total).toBe(2);
    expect(model.limit).toBe(1);
    expect(model.calls.map((call) => call.id)).toEqual(["c"]);

    const windowed = filterCalls(calls, search, {
      since: "2026-11-02T00:00:00Z",
      until: "2026-11-02T00:00:00Z",
      limit: 25,
      offset: 0,
    });
    expect(windowed.calls.map((call) => call.id)).toEqual(["b"]);

    const late = filterCalls(calls, search, { q: "warranty", limit: 25, offset: 0 });
    expect(late.calls.map((call) => call.id)).toEqual(["c"]);
  });

  it("reads the calls query the dashboard builds", () => {
    expect(callsQueryFilters("/api/calls?model=llama-3.1-8b-instant&status=error&q=%25&limit=25&offset=25")).toEqual({
      model: "llama-3.1-8b-instant",
      status: "error",
      q: "%",
      since: undefined,
      until: undefined,
      limit: 25,
      offset: 25,
    });
    expect(callsQueryFilters("/api/calls/call_0001")).toBeNull();
  });

  it("maps API paths onto the exported JSON files", () => {
    expect(demoAssetPath("/api/meta")).toBe("/demo/meta.json");
    expect(demoAssetPath("/api/metrics/summary")).toBe("/demo/metrics/summary.json");
    expect(demoAssetPath("/api/calls/call_0001")).toBe("/demo/calls/call_0001.json");
    expect(demoAssetPath("/api/evals/comparisons")).toBe("/demo/evals/comparisons.json");
    expect(demoAssetPath("/api/evals/comparisons/cmp_3b_costcut")).toBe(
      "/demo/evals/comparisons/cmp_3b_costcut.json",
    );
    expect(demoAssetPath("/api/health")).toBeNull();
  });
});
