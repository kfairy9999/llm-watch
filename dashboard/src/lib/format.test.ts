import { formatDelta, formatMs, formatTokens, formatUsd } from "./format";

describe("formatters", () => {
  it("keeps small model costs readable", () => {
    expect(formatUsd(0)).toBe("$0");
    expect(formatUsd(0.0000164)).toBe("$0.000016");
    expect(formatUsd(0.03124)).toBe("$0.0312");
    expect(formatUsd(12.5)).toBe("$12.50");
  });

  it("formats latency, tokens, and signed deltas", () => {
    expect(formatMs(340)).toBe("340 ms");
    expect(formatMs(1400)).toBe("1.40 s");
    expect(formatMs(null)).toBe("—");
    expect(formatTokens(48200)).toBe("48,200");
    expect(formatDelta(0.333)).toBe("+0.333");
    expect(formatDelta(-0.49)).toBe("-0.490");
    expect(formatDelta(0)).toBe("0.000");
  });
});
