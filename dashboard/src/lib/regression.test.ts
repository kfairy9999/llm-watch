import { bannerTone, gateCopy, gateVerdict, intervalSentence } from "./regression";
import { buildCallsQuery } from "./filters";

describe("gate verdict", () => {
  it("fails closed when the gate fails, even if the mean improved", () => {
    expect(gateVerdict({ failed_gate: true, significant_improvement: true })).toBe("fail");
    expect(gateCopy("fail").title).toBe("Gate failed");
  });

  it("names an improvement only when the gate passed", () => {
    expect(gateVerdict({ failed_gate: false, significant_improvement: true })).toBe("pass-improvement");
    expect(gateCopy("pass-improvement").tone).toBe("good");
    expect(gateVerdict({ failed_gate: false, significant_improvement: false })).toBe("pass-inconclusive");
  });

  it("explains the bootstrap interval in plain language", () => {
    const text = intervalSentence({
      delta: -0.49,
      ci_low: -0.72,
      ci_high: -0.21,
      n_boot: 2000,
      significant_regression: true,
      significant_improvement: false,
      pass_flips: 6,
    });
    expect(text).toContain("entirely below zero");
    expect(text).toContain("6 tests flipped");
  });
});

describe("banner tone", () => {
  it("distinguishes synthetic, mixed, and recorded ledgers", () => {
    expect(bannerTone(null)).toBe("none");
    expect(bannerTone("Synthetic demo data. Not a live provider trace.")).toBe("synthetic");
    expect(bannerTone("This ledger mixes synthetic demo rows with recorded calls.")).toBe("mixed");
  });
});

describe("call query", () => {
  it("omits empty filters and keeps the search", () => {
    expect(buildCallsQuery({ model: "", status: "error", q: "Austin", limit: 25, offset: 50 })).toBe(
      "/api/calls?status=error&q=Austin&limit=25&offset=50",
    );
  });
});
