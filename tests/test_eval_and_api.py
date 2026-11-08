from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from llmwatch.api.main import create_app
from llmwatch.cli import main
from llmwatch.eval.report import render_report
from llmwatch.eval.runner import compare_runs, run_suite
from llmwatch.eval.scorers import score_output
from llmwatch.eval.stats import bootstrap_mean_ci
from llmwatch.eval.suite import ScorerSpec, load_fixtures, load_suite
from llmwatch.notice import MIXED_DISCLAIMER, SYNTHETIC_DISCLAIMER, disclaimer_for
from llmwatch.pricing import load_price_table
from llmwatch.seed import CALL_COUNT, seed_demo
from llmwatch.store import Store
from tests.conftest import sample_call

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "llmwatch" / "suites" / "customer_support.yaml"
FIXTURES = ROOT / "llmwatch" / "suites" / "customer_support_outputs.yaml"


def _run_pair(tmp_path, model_b: str, *, n_boot: int = 400):
    suite, fingerprint = load_suite(SUITE)
    fixtures = load_fixtures(FIXTURES)
    from llmwatch.providers import fixture_completion_fn

    complete = fixture_completion_fn(fixtures, simulate=True, seed=1)
    store = Store(tmp_path / "t.db")
    store.migrate()
    table = load_price_table()
    shared = dict(
        complete_fn=complete,
        store=store,
        created_at="2026-11-07T18:00:00Z",
        synthetic=True,
        fingerprint=fingerprint,
        provenance="scripted-fixture",
        price_table=table,
    )
    run_a = run_suite(suite, model="llama-3.1-8b-instant", run_id="run_a", label="baseline", **shared)
    run_b = run_suite(suite, model=model_b, run_id="run_b", label="candidate", **shared)
    return compare_runs(
        run_a,
        run_b,
        store=store,
        comparison_id="cmp_test",
        created_at="2026-11-07T18:00:00Z",
        name="test",
        gate_fail_on_pass_flip=True,
        gate_fail_on_significant_regression=True,
        n_boot=n_boot,
        seed=1,
    )


def test_bootstrap_properties():
    mean, low, high = bootstrap_mean_ci([0.5, 0.5, 0.5], n_boot=50, seed=1)
    assert mean == low == high == 0.5
    _mean, low, high = bootstrap_mean_ci([-1, -1, -1, -1], n_boot=100, seed=2)
    assert high < 0
    _mean, low, high = bootstrap_mean_ci([-1, 1], n_boot=300, seed=3)
    assert low < 0 < high
    again = bootstrap_mean_ci([-1, 0, 1, 0.5], n_boot=200, seed=4)
    assert again == bootstrap_mean_ci([-1, 0, 1, 0.5], n_boot=200, seed=4)
    only = bootstrap_mean_ci([0.2], n_boot=10, seed=0)
    assert only == (0.2, 0.2, 0.2)
    with pytest.raises(ValueError):
        bootstrap_mean_ci([], n_boot=10)


def test_scorers_cover_the_five_kinds():
    assert score_output(ScorerSpec(type="exact", expected="Paris"), " paris ").passed is False
    assert score_output(ScorerSpec(type="exact", expected="Paris", case_sensitive=False), " paris ").passed
    assert score_output(ScorerSpec(type="regex", pattern=r"\b14[- ]days?\b"), "in 14 days.").passed
    assert score_output(ScorerSpec(type="regex", pattern="secret", forbid=True), "nothing to see").passed
    assert not score_output(ScorerSpec(type="regex", pattern="secret", forbid=True), "secret").passed
    assert score_output(ScorerSpec(type="numeric", value=3.84, tolerance=0.01), "3.84").passed
    assert not score_output(ScorerSpec(type="numeric", value=3.84, tolerance=0.01), "4").passed
    assert not score_output(ScorerSpec(type="numeric", value=1), "none").passed
    schema = {
        "type": "object",
        "required": ["id"],
        "properties": {"id": {"type": "string"}},
    }
    fenced = '```json\n{"id":"TCK-1042"}\n```'
    assert score_output(ScorerSpec(type="json_schema", json_schema=schema), fenced).passed
    assert not score_output(ScorerSpec(type="json_schema", json_schema=schema), "not json").passed
    assert not score_output(ScorerSpec(type="json_schema", json_schema=schema), "{}").passed
    judged = score_output(
        ScorerSpec(type="llm_judge", mode="mock", keywords=["sorry", "replac"], min_chars=20, pass_threshold=0.7),
        "I am sorry and I will send a replacement.",
    )
    assert judged.passed
    assert "offline heuristic" in judged.detail
    weak = score_output(
        ScorerSpec(type="llm_judge", mode="mock", keywords=["sorry", "replac"], pass_threshold=0.7),
        "That happens sometimes.",
    )
    assert not weak.passed
    live = score_output(
        ScorerSpec(type="llm_judge", mode="live", rubric="Be polite.", pass_threshold=0.7),
        "hello",
        judge=lambda _messages: '{"score": 0.9, "reason": "polite enough"}',
    )
    assert live.passed
    assert live.score == pytest.approx(0.9)
    missing = score_output(
        ScorerSpec(type="llm_judge", mode="live", rubric="Be polite."),
        "hello",
    )
    assert not missing.passed


def test_raised_completion_fails_the_test_and_the_run_continues(tmp_path):
    suite, _fp = load_suite(SUITE)

    def complete(_model, test):
        if test.id == "eta-days":
            raise RuntimeError("provider down")
        return "unused"

    store = Store(tmp_path / "t.db")
    store.migrate()
    run = run_suite(
        suite,
        model="llama-3.1-8b-instant",
        complete_fn=complete,
        store=store,
        run_id="run_err",
        created_at="2026-11-07T00:00:00Z",
        provenance="live",
    )
    by_id = {item.test_id: item for item in run.results}
    assert "RuntimeError" in by_id["eta-days"].error
    assert by_id["eta-days"].passed is False
    assert len(run.results) == 12


def test_demo_suite_70b_improves_and_3b_regresses(tmp_path):
    improved = _run_pair(tmp_path, "llama-3.3-70b-versatile")
    assert improved["pass_flips"] == 0
    assert improved["significant_improvement"]
    assert not improved["significant_regression"]
    assert improved["failed_gate"] is False
    assert improved["metrics_simulated"] is True
    assert "Scripted answers" in improved["provenance_note"]
    deltas = [item["delta"] for item in improved["tests"]]
    mean, low, high = bootstrap_mean_ci(deltas, n_boot=improved["n_boot"], seed=improved["seed"])
    assert mean == pytest.approx(improved["delta"])
    assert low == pytest.approx(improved["ci_low"])
    assert high == pytest.approx(improved["ci_high"])

    regressed = _run_pair(tmp_path / "b", "llama-3.2-3b-preview")
    assert regressed["pass_flips"] >= 1
    assert regressed["significant_regression"]
    assert regressed["failed_gate"] is True
    report = render_report(regressed)
    assert "GATE     fail" in report
    assert "VERDICT  significant regression" in report


def test_cli_exit_codes(tmp_path):
    db = tmp_path / "cli.db"
    common = [
        "--suite",
        str(SUITE),
        "--fixture",
        str(FIXTURES),
        "--db",
        str(db),
        "--n-boot",
        "400",
        "--json",
    ]
    fail = main(
        [
            "eval",
            "run",
            *common,
            "--model-a",
            "llama-3.1-8b-instant",
            "--model-b",
            "llama-3.2-3b-preview",
        ]
    )
    assert fail == 1
    ok = main(
        [
            "eval",
            "run",
            *common,
            "--model-a",
            "llama-3.1-8b-instant",
            "--model-b",
            "llama-3.3-70b-versatile",
        ]
    )
    assert ok == 0
    missing = main(
        [
            "eval",
            "run",
            "--suite",
            str(SUITE),
            "--model-a",
            "missing-model",
            "--model-b",
            "llama-3.1-8b-instant",
            "--db",
            str(db),
        ]
    )
    assert missing == 2


def test_seed_is_synthetic_priced_and_labeled(tmp_path):
    path = tmp_path / "demo.db"
    first = seed_demo(path)
    second = seed_demo(path)
    assert first["seeded"] is True
    assert second["seeded"] is False
    store = Store(path)
    assert store.count_calls() == CALL_COUNT
    table = load_price_table()
    _total, rows = store.list_calls(limit=100)
    assert rows
    models = set()
    for row in store.call_metrics():
        models.add(row["model"])
        cost, _source = table.compute_cost(row["model"], row["prompt_tokens"], row["completion_tokens"])
        if row["status"] == "ok":
            assert row["cost_usd"] == pytest.approx(cost)
        else:
            assert row["cost_usd"] == 0
        assert row["synthetic"] == 1
    assert models == {"llama-3.1-8b-instant", "llama-3.3-70b-versatile"}
    assert "llama-3.2-3b-preview" not in models
    comparisons = store.list_comparisons()
    by_id = {item["id"]: item for item in comparisons}
    assert by_id["cmp_3b_costcut"]["failed_gate"] is True
    assert by_id["cmp_70b_candidate"]["failed_gate"] is False
    detail = store.get_call(rows[0]["id"])
    assert detail["data_label"] == "synthetic demo"
    assert "fictional" in detail["messages"][0]["content"]


def test_search_does_not_treat_percent_as_a_wildcard(tmp_path):
    path = tmp_path / "demo.db"
    seed_demo(path)
    app = create_app(path, seed=False)
    client = TestClient(app)
    austin = client.get("/api/calls", params={"q": "Austin", "limit": 100})
    assert austin.status_code == 200
    assert austin.json()["total"] > 0
    assert all("Austin" in call["prompt_preview"] or "Austin" in call["response_preview"] for call in austin.json()["calls"])
    wildcard = client.get("/api/calls", params={"q": "%"}).json()
    assert wildcard["total"] == 0
    only_8b = client.get("/api/calls", params={"model": "llama-3.1-8b-instant", "limit": 100}).json()
    assert only_8b["total"] > 0
    assert {call["model"] for call in only_8b["calls"]} == {"llama-3.1-8b-instant"}


def test_api_meta_timeseries_and_comparison(tmp_path):
    path = tmp_path / "demo.db"
    seed_demo(path)
    client = TestClient(create_app(path, seed=False))
    meta = client.get("/api/meta").json()
    assert meta["disclaimer"] == SYNTHETIC_DISCLAIMER
    assert meta["synthetic_calls"] == CALL_COUNT
    assert meta["recorded_calls"] == 0
    assert "Synthetic demo data" in meta["disclaimer"]
    health = client.get("/api/health").json()
    assert health["ok"] is True
    series = client.get("/api/metrics/timeseries").json()
    assert series["synthetic"] is True
    assert sum(point["calls"] for point in series["points"]) == series["total_calls"] == CALL_COUNT
    dates = [point["date"] for point in series["points"]]
    assert dates == sorted(dates)
    from datetime import date as date_cls

    parsed = [date_cls.fromisoformat(item) for item in dates]
    assert all((b - a).days == 1 for a, b in zip(parsed, parsed[1:]))
    summary = client.get("/api/metrics/summary").json()
    assert summary["latency_basis"] == "successful calls"
    assert 0 <= summary["error_rate"] < 1
    comparison = client.get("/api/evals/comparisons/cmp_3b_costcut").json()
    assert comparison["significant_regression"] is True
    assert any(test["flag"] == "regression" for test in comparison["tests"])
    missing = client.get("/api/calls/does-not-exist")
    assert missing.status_code == 404


def test_real_rows_are_not_labeled_synthetic_and_mix_is(tmp_path):
    path = tmp_path / "real.db"
    store = Store(path)
    store.migrate()
    store.insert_call(sample_call())
    client = TestClient(create_app(path, seed=False))
    meta = client.get("/api/meta").json()
    assert meta["disclaimer"] is None
    assert meta["recorded_calls"] == 1
    assert meta["synthetic_calls"] == 0
    seed_demo(tmp_path / "mix.db")
    mix = Store(tmp_path / "mix.db")
    mix.insert_call(sample_call(id="call_live"))
    mixed = TestClient(create_app(tmp_path / "mix.db", seed=False)).get("/api/meta").json()
    assert mixed["disclaimer"] == MIXED_DISCLAIMER
    assert disclaimer_for(synthetic_calls=0, recorded_calls=0) is None


def test_dashboard_copy_matches_the_api_disclaimer():
    text = (ROOT / "dashboard" / "src" / "copy.ts").read_text(encoding="utf-8")
    assert SYNTHETIC_DISCLAIMER in text
    assert MIXED_DISCLAIMER in text


def test_compose_and_workflow_exist():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    assert "api" in compose["services"]
    assert "dashboard" in compose["services"]
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "pytest" in workflow
    assert "npm test" in workflow
    assert "npm run build" in workflow


def test_filters_escape_underscore(tmp_path):
    store = Store(tmp_path / "t.db")
    store.migrate()
    store.insert_call(sample_call(id="a", prompt=[{"role": "user", "content": "100% sure"}]))
    store.insert_call(sample_call(id="b", prompt=[{"role": "user", "content": "other"}]))
    total, rows = store.list_calls(q="100% sure")
    assert total == 1
    assert rows[0]["id"] == "a"
    total, _rows = store.list_calls(q="_")
    assert total == 0
    json.dumps(store.get_call("a"))
