export type GateVerdict = "fail" | "pass-improvement" | "pass-inconclusive";

export function gateVerdict(input: {
  failed_gate: boolean;
  significant_improvement: boolean;
}): GateVerdict {
  if (input.failed_gate) return "fail";
  if (input.significant_improvement) return "pass-improvement";
  return "pass-inconclusive";
}

export function gateCopy(verdict: GateVerdict): { title: string; tone: "bad" | "good" | "neutral" } {
  if (verdict === "fail") return { title: "Gate failed", tone: "bad" };
  if (verdict === "pass-improvement") return { title: "Gate passed · improvement", tone: "good" };
  return { title: "Gate passed · inconclusive", tone: "neutral" };
}

export function bannerTone(disclaimer: string | null): "synthetic" | "mixed" | "none" {
  if (!disclaimer) return "none";
  if (disclaimer.startsWith("This ledger mixes")) return "mixed";
  return "synthetic";
}

export function intervalSentence(input: {
  delta: number;
  ci_low: number;
  ci_high: number;
  n_boot: number;
  significant_regression: boolean;
  significant_improvement: boolean;
  pass_flips: number;
}): string {
  const sign = input.delta > 0 ? "+" : "";
  const lead = `Mean score moved by ${sign}${input.delta.toFixed(3)}. A 95% bootstrap confidence interval is [${input.ci_low.toFixed(3)}, ${input.ci_high.toFixed(3)}] (${input.n_boot.toLocaleString("en-US")} resamples).`;
  let middle = " The interval crosses zero, so the mean shift is inconclusive.";
  if (input.significant_regression) {
    middle = " The interval is entirely below zero, so this drop is flagged as a significant regression.";
  } else if (input.significant_improvement) {
    middle = " The interval is entirely above zero, so this gain is flagged as a significant improvement.";
  }
  const flips =
    input.pass_flips > 0
      ? ` ${input.pass_flips} test${input.pass_flips === 1 ? "" : "s"} flipped from pass to fail.`
      : "";
  return lead + middle + flips;
}
