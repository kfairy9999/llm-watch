"""Plain-text comparison report for the CLI and CI logs."""

from __future__ import annotations


def render_report(comparison: dict) -> str:
    lines = [
        f"{comparison['name']}",
        f"suite {comparison['suite_name']}   {comparison['model_a']}  ->  {comparison['model_b']}",
        f"provenance  {comparison.get('provenance_note', comparison.get('provenance', ''))}",
        "",
        f"{'test':<22} {'A':>7} {'B':>7} {'delta':>8}  flag",
    ]
    for test in comparison["tests"]:
        flag = "" if test["flag"] == "unchanged" else test["flag"]
        lines.append(
            f"{test['test_id']:<22} {test['score_a']:7.3f} {test['score_b']:7.3f} {test['delta']:+8.3f}  {flag}"
        )
    lines.append("")
    lines.append(
        f"mean {comparison['mean_a']:.3f} -> {comparison['mean_b']:.3f}   "
        f"delta {comparison['delta']:+.3f}   "
        f"95% CI [{comparison['ci_low']:+.3f}, {comparison['ci_high']:+.3f}]   "
        f"n_boot={comparison['n_boot']} seed={comparison['seed']}"
    )
    lines.append(
        f"pass rate {comparison['pass_rate_a']:.3f} -> {comparison['pass_rate_b']:.3f}   "
        f"pass flips {comparison['pass_flips']}   pass gains {comparison['pass_gains']}"
    )
    if comparison.get("metrics_simulated"):
        lines.append("ops metrics  simulated for this fixture run; scores are not")
    if comparison["significant_regression"]:
        verdict = "significant regression"
    elif comparison["significant_improvement"]:
        verdict = "significant improvement"
    else:
        verdict = "inconclusive"
    lines.append(f"VERDICT  {verdict}")
    lines.append("GATE     fail" if comparison["failed_gate"] else "GATE     pass")
    lines.append(
        "CI is a paired percentile bootstrap of the mean per-test score delta. It is a gate, not a research claim."
    )
    return "\n".join(lines)
