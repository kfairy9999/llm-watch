"""Run a suite against one model and compare two finished runs."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Callable

from llmwatch.eval.scorers import JudgeFn, score_output
from llmwatch.eval.stats import bootstrap_mean_ci
from llmwatch.eval.suite import SuiteSpec, TestCase
from llmwatch.notice import PRICE_NOTE
from llmwatch.pricing import PriceTable, load_price_table
from llmwatch.store import Ledger
from llmwatch.text import estimate_tokens, render_messages, user_text

CompleteFn = Callable[[str, TestCase], "str | Completion"]


@dataclass
class Completion:
    text: str
    latency_ms: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    metrics_simulated: bool = False


@dataclass
class TestResult:
    test_id: str
    description: str
    prompt: str
    output: str
    score: float
    passed: bool
    scorers: list[dict]
    latency_ms: float
    cost_usd: float
    prompt_tokens: int
    completion_tokens: int
    metrics_simulated: bool
    error: str | None = None

    def to_row(self, run_id: str) -> dict:
        return {
            "id": f"res_{run_id}_{self.test_id}",
            "test_id": self.test_id,
            "description": self.description,
            "prompt": self.prompt,
            "output": self.output,
            "score": self.score,
            "passed": self.passed,
            "scorers": self.scorers,
            "latency_ms": self.latency_ms,
            "cost_usd": self.cost_usd,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "metrics_simulated": self.metrics_simulated,
            "error": self.error,
        }


@dataclass
class Run:
    id: str
    created_at: str
    suite_name: str
    suite_fingerprint: str
    model: str
    label: str
    synthetic: bool
    provenance: str
    results: list[TestResult] = field(default_factory=list)

    @property
    def mean_score(self) -> float:
        if not self.results:
            return 0.0
        return sum(item.score for item in self.results) / len(self.results)

    @property
    def pass_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for item in self.results if item.passed) / len(self.results)


def run_suite(
    suite: SuiteSpec,
    *,
    model: str,
    complete_fn: CompleteFn,
    store: Ledger | None,
    run_id: str,
    created_at: str,
    label: str = "",
    synthetic: bool = False,
    fingerprint: str = "inline",
    provenance: str = "live",
    price_table: PriceTable | None = None,
    judge: JudgeFn | None = None,
) -> Run:
    table = price_table or load_price_table()
    run = Run(
        id=run_id,
        created_at=created_at,
        suite_name=suite.name,
        suite_fingerprint=fingerprint,
        model=model,
        label=label,
        synthetic=synthetic,
        provenance=provenance,
    )
    for test in suite.tests:
        run.results.append(_score_test(test, model, complete_fn, table, judge))
    if store is not None:
        store.insert_run(_run_row(run), [item.to_row(run.id) for item in run.results])
    return run


def compare_runs(
    run_a: Run,
    run_b: Run,
    *,
    store: Ledger | None,
    comparison_id: str,
    created_at: str,
    name: str,
    gate_fail_on_pass_flip: bool = True,
    gate_fail_on_significant_regression: bool = True,
    delta_threshold: float = 0.0,
    n_boot: int = 2000,
    alpha: float = 0.05,
    seed: int = 0,
    narrative: str = "",
    synthetic: bool | None = None,
) -> dict:
    if run_a.suite_name != run_b.suite_name:
        raise ValueError("cannot compare runs from different suites")
    by_a = {item.test_id: item for item in run_a.results}
    by_b = {item.test_id: item for item in run_b.results}
    if list(by_a) != list(by_b):
        raise ValueError("runs scored different tests")
    tests: list[dict] = []
    deltas: list[float] = []
    pass_deltas: list[float] = []
    pass_flips = 0
    pass_gains = 0
    for test_id, left in by_a.items():
        right = by_b[test_id]
        delta = right.score - left.score
        deltas.append(delta)
        pass_deltas.append(float(right.passed) - float(left.passed))
        if left.passed and not right.passed:
            pass_flips += 1
            flag = "regression"
        elif not left.passed and right.passed:
            pass_gains += 1
            flag = "improvement"
        elif delta < -1e-9:
            flag = "regression"
        elif delta > 1e-9:
            flag = "improvement"
        else:
            flag = "unchanged"
        tests.append(
            {
                "test_id": test_id,
                "description": left.description or right.description,
                "prompt": left.prompt,
                "output_a": left.output,
                "output_b": right.output,
                "score_a": left.score,
                "score_b": right.score,
                "delta": delta,
                "passed_a": left.passed,
                "passed_b": right.passed,
                "flag": flag,
                "scorers_a": left.scorers,
                "scorers_b": right.scorers,
                "error_a": left.error,
                "error_b": right.error,
            }
        )
    mean, low, high = bootstrap_mean_ci(deltas, n_boot=n_boot, alpha=alpha, seed=seed)
    significant_regression = high < -delta_threshold
    significant_improvement = low > delta_threshold
    failed_gate = (
        gate_fail_on_significant_regression and significant_regression
    ) or (gate_fail_on_pass_flip and pass_flips > 0)
    metrics_simulated = any(item.metrics_simulated for item in run_a.results + run_b.results)
    summary = {
        "id": comparison_id,
        "name": name,
        "created_at": created_at,
        "suite_name": run_a.suite_name,
        "suite_fingerprint": run_a.suite_fingerprint,
        "run_a_id": run_a.id,
        "run_b_id": run_b.id,
        "model_a": run_a.model,
        "model_b": run_b.model,
        "label_a": run_a.label,
        "label_b": run_b.label,
        "n_tests": len(tests),
        "mean_a": run_a.mean_score,
        "mean_b": run_b.mean_score,
        "delta": mean,
        "ci_low": low,
        "ci_high": high,
        "alpha": alpha,
        "n_boot": n_boot,
        "seed": seed,
        "delta_threshold": delta_threshold,
        "significant_regression": significant_regression,
        "significant_improvement": significant_improvement,
        "pass_rate_a": run_a.pass_rate,
        "pass_rate_b": run_b.pass_rate,
        "pass_flips": pass_flips,
        "pass_gains": pass_gains,
        "failed_gate": failed_gate,
        "provenance": run_b.provenance if run_a.provenance == run_b.provenance else "mixed",
        "provenance_note": _provenance_note(run_a.provenance, run_b.provenance),
        "narrative": narrative,
        "metrics_simulated": metrics_simulated,
        "mean_latency_a": _mean(run_a.results, "latency_ms"),
        "mean_latency_b": _mean(run_b.results, "latency_ms"),
        "mean_cost_a": _mean(run_a.results, "cost_usd"),
        "mean_cost_b": _mean(run_b.results, "cost_usd"),
        "price_note": PRICE_NOTE,
        "synthetic": run_a.synthetic and run_b.synthetic if synthetic is None else synthetic,
        "tests": tests,
        "method": (
            "Paired percentile bootstrap of the mean per-test score delta. "
            "A pass-to-fail flip fails the gate even when the mean CI is inconclusive."
        ),
    }
    if store is not None:
        store.insert_comparison(
            {
                "id": comparison_id,
                "created_at": created_at,
                "suite_name": run_a.suite_name,
                "run_a_id": run_a.id,
                "run_b_id": run_b.id,
                "synthetic": summary["synthetic"],
                "summary": summary,
            }
        )
    return summary


def _score_test(
    test: TestCase,
    model: str,
    complete_fn: CompleteFn,
    table: PriceTable,
    judge: JudgeFn | None,
) -> TestResult:
    started = time.perf_counter()
    error: str | None = None
    raw: str | Completion
    try:
        raw = complete_fn(model, test)
    except Exception as exc:
        raw = Completion(text="")
        error = f"{type(exc).__name__}: {exc}"
    wall_ms = (time.perf_counter() - started) * 1000
    if isinstance(raw, Completion):
        text = raw.text
        latency = wall_ms if raw.latency_ms is None else raw.latency_ms
        simulated = raw.metrics_simulated
        prompt_tokens = raw.prompt_tokens
        completion_tokens = raw.completion_tokens
    else:
        text = str(raw)
        latency = wall_ms
        simulated = False
        prompt_tokens = None
        completion_tokens = None
    if prompt_tokens is None or completion_tokens is None:
        prompt_tokens = estimate_tokens(render_messages(test.messages))
        completion_tokens = estimate_tokens(text)
    scored = [score_output(spec, text, judge=judge) for spec in test.scorers]
    finite = []
    for item in scored:
        if not math.isfinite(item.score):
            item.score = 0.0
            item.passed = False
        finite.append(item)
    score = sum(item.score for item in finite) / len(finite)
    passed = all(item.passed for item in finite) and error is None
    cost, _source = table.compute_cost(model, prompt_tokens, completion_tokens)
    return TestResult(
        test_id=test.id,
        description=test.description,
        prompt=user_text(test.messages),
        output=text,
        score=score,
        passed=passed,
        scorers=[item.to_dict() for item in finite],
        latency_ms=round(float(latency), 3),
        cost_usd=cost,
        prompt_tokens=int(prompt_tokens),
        completion_tokens=int(completion_tokens),
        metrics_simulated=simulated or (isinstance(raw, Completion) and raw.metrics_simulated),
        error=error,
    )


def _run_row(run: Run) -> dict:
    return {
        "id": run.id,
        "created_at": run.created_at,
        "suite_name": run.suite_name,
        "suite_fingerprint": run.suite_fingerprint,
        "model": run.model,
        "label": run.label,
        "synthetic": run.synthetic,
        "provenance": run.provenance,
        "mean_score": run.mean_score,
        "pass_rate": run.pass_rate,
        "n_tests": len(run.results),
        "summary": {},
    }


def _mean(results: list[TestResult], attr: str) -> float:
    if not results:
        return 0.0
    return sum(getattr(item, attr) or 0 for item in results) / len(results)


def _provenance_note(left: str, right: str) -> str:
    if left == right == "scripted-fixture":
        return (
            "Scripted answers, real scorers. Graded by the llm-watch runner on checked-in outputs. "
            "Not a live provider result."
        )
    if left == right == "live":
        return "Scored from live model outputs recorded by this runner."
    return "The two runs do not share a provenance label. Read each run before quoting the delta."
