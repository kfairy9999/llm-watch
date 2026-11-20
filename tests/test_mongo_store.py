"""MongoDB ledger tests. mongomock stands in for a server, so CI needs no cluster."""

from __future__ import annotations

import builtins
import json
from pathlib import Path

import httpx
import mongomock
import pytest
import pymongo
from fastapi.testclient import TestClient

from llmwatch.api.main import create_app
from llmwatch.api.metrics import summarize
from llmwatch.cli import main
from llmwatch.client import WatchClient
from llmwatch.eval.runner import compare_runs, run_suite
from llmwatch.eval.suite import load_fixtures, load_suite
from llmwatch.mongo_store import MongoStore
from llmwatch.providers import fixture_completion_fn
from llmwatch.store import Store, open_store
from tests.conftest import sample_call

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "llmwatch" / "suites" / "customer_support.yaml"
FIXTURES = ROOT / "llmwatch" / "suites" / "customer_support_outputs.yaml"


def _mongo() -> MongoStore:
    store = MongoStore(
        "mongodb://localhost:27017",
        database="llmwatch",
        client=mongomock.MongoClient(),
    )
    store.migrate()
    store.migrate()
    return store


def _run(run_id: str) -> dict:
    return {
        "id": run_id,
        "created_at": "2026-11-07T18:00:00Z",
        "suite_name": "customer_support",
        "suite_fingerprint": "fp",
        "model": "llama-3.1-8b-instant",
        "label": "A",
        "synthetic": False,
        "provenance": "live",
        "mean_score": 1.0,
        "pass_rate": 1.0,
        "n_tests": 1,
        "summary": {},
    }


def _result(run_id: str, test_id: str) -> dict:
    return {
        "id": f"res_{run_id}_{test_id}",
        "test_id": test_id,
        "description": test_id,
        "prompt": "When does it ship?",
        "output": "14 days",
        "score": 1.0,
        "passed": True,
        "scorers": [{"type": "exact", "passed": True, "score": 1.0}],
        "latency_ms": 12.5,
        "cost_usd": 0.0,
        "prompt_tokens": 4,
        "completion_tokens": 2,
        "metrics_simulated": False,
        "error": None,
    }


def _comparison(run_a: str, run_b: str, comparison_id: str = "cmp_test") -> dict:
    return {
        "id": comparison_id,
        "created_at": "2026-11-07T18:00:00Z",
        "suite_name": "customer_support",
        "run_a_id": run_a,
        "run_b_id": run_b,
        "synthetic": False,
        "summary": {
            "name": "t",
            "significant_regression": False,
            "failed_gate": False,
            "model_a": "a",
            "model_b": "b",
        },
    }


def _use_mongomock(monkeypatch, client: mongomock.MongoClient) -> None:
    monkeypatch.setenv("LLMWATCH_MONGODB_URI", "mongodb://example.invalid")
    monkeypatch.setattr(pymongo, "MongoClient", lambda *args, **kwargs: client)


def test_blank_uri_stays_on_sqlite(tmp_path, monkeypatch):
    monkeypatch.setenv("LLMWATCH_MONGODB_URI", "   ")
    store = open_store(tmp_path / "t.db")
    assert isinstance(store, Store)
    store.migrate()
    store.insert_call(sample_call())
    assert store.count_calls() == 1
    assert (tmp_path / "t.db").exists()


def test_store_path_ignores_mongodb_uri(tmp_path, monkeypatch):
    monkeypatch.setenv("LLMWATCH_MONGODB_URI", "mongodb://example.invalid")
    store = Store(tmp_path / "t.db")
    store.migrate()
    store.insert_call(sample_call())
    assert store.get_call("call_test")["model"] == "llama-3.1-8b-instant"
    assert (tmp_path / "t.db").exists()


def test_open_store_selects_mongodb_database(tmp_path, monkeypatch):
    monkeypatch.setenv("LLMWATCH_MONGODB_URI", "mongodb://example.invalid")
    monkeypatch.delenv("LLMWATCH_MONGODB_DB", raising=False)
    client = mongomock.MongoClient()
    store = open_store(tmp_path / "ignored.db", client=client)
    assert isinstance(store, MongoStore)
    assert store.database_name == "llmwatch"
    store.insert_call(sample_call())
    assert client["llmwatch"]["calls"].count_documents({}) == 1
    assert not (tmp_path / "ignored.db").exists()

    monkeypatch.setenv("LLMWATCH_MONGODB_DB", "audit")
    named = open_store(client=mongomock.MongoClient())
    assert named.database_name == "audit"
    monkeypatch.setenv("LLMWATCH_MONGODB_DB", "   ")
    fallback = open_store(client=mongomock.MongoClient())
    assert fallback.database_name == "llmwatch"


def test_client_argument_requires_the_uri():
    with pytest.raises(ValueError, match="LLMWATCH_MONGODB_URI"):
        open_store(client=mongomock.MongoClient())


def test_missing_pymongo_names_the_extra(monkeypatch):
    monkeypatch.setenv("LLMWATCH_MONGODB_URI", "mongodb://example.invalid")
    real_import = builtins.__import__

    def guarded(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "pymongo" or name.startswith("pymongo."):
            raise ImportError("blocked for test")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded)
    with pytest.raises(RuntimeError, match=r"llm-watch\[mongodb\]"):
        open_store()


def test_calls_round_trip_filter_and_replace():
    store = _mongo()
    store.insert_call(sample_call(id="call_early", created_at="2026-11-01T00:00:00Z"))
    store.insert_call(
        sample_call(
            id="call_mid",
            created_at="2026-11-02T00:00:00Z",
            prompt=[{"role": "user", "content": "100% sure"}],
        )
    )
    store.insert_call(
        sample_call(
            id="call_late",
            created_at="2026-11-03T00:00:00Z",
            model="other-model",
            status="error",
            error_type="rate_limit",
            error_message="slow down",
            http_status=429,
            response=None,
            response_text="",
            synthetic=True,
            streaming=True,
        )
    )
    store.insert_call(sample_call(id="call_b", created_at="2026-11-04T00:00:00Z"))
    store.insert_call(sample_call(id="call_a", created_at="2026-11-04T00:00:00Z"))

    assert store.count_calls() == 5
    assert store.get_call("missing") is None
    detail = store.get_call("call_early")
    assert detail["messages"] == [{"role": "user", "content": "Hi"}]
    assert detail["response"]["choices"][0]["message"]["content"] == "Hello"
    assert detail["metadata"]["route"] == "support"
    assert detail["synthetic"] is False
    assert "prompt_json" not in detail

    raw = store.db["calls"].find_one({"_id": "call_early"})
    assert raw["prompt"] == [{"role": "user", "content": "Hi"}]
    assert raw["metadata"] == {"route": "support"}
    assert "prompt_json" not in raw
    assert "response_json" not in raw

    _total, rows = store.list_calls()
    assert [row["id"] for row in rows] == ["call_b", "call_a", "call_late", "call_mid", "call_early"]
    _total, page = store.list_calls(limit=1, offset=2)
    assert page[0]["id"] == "call_late"
    assert _total == 5

    total, rows = store.list_calls(since="2026-11-02T00:00:00Z", until="2026-11-02T00:00:00Z")
    assert total == 1 and rows[0]["id"] == "call_mid"
    total, rows = store.list_calls(status="error")
    assert [row["id"] for row in rows] == ["call_late"]
    assert rows[0]["streaming"] is True
    error = store.get_call("call_late")
    assert error["http_status"] == 429
    assert error["response"] is None
    assert error["data_label"] == "synthetic demo"
    total, rows = store.list_calls(model="other-model")
    assert total == 1 and rows[0]["id"] == "call_late"

    total, rows = store.list_calls(q="100% sure")
    assert total == 1 and rows[0]["id"] == "call_mid"
    assert store.list_calls(q="%")[0] == 1
    assert store.list_calls(q="_")[0] == 0
    assert store.list_calls(q=".*")[0] == 0
    assert store.list_calls(q="HI")[0] == 4

    assert store.distinct_models() == ["llama-3.1-8b-instant", "other-model"]
    counts = store.counts()
    assert counts["synthetic_calls"] == 1
    assert counts["recorded_calls"] == 4
    assert summarize(store.call_metrics())["calls"] == 5

    store.insert_call(sample_call(id="call_early", model="replaced"))
    assert store.count_calls() == 5
    assert store.get_call("call_early")["model"] == "replaced"

    index = store.call_search_index()
    assert "100% sure" in index["call_mid"]["prompt_json"]
    assert store.list_calls(q="100% sure")[0] == 1

    store.clear()
    assert store.count_calls() == 0
    assert store.list_comparisons() == []
    assert store.counts() == {
        "synthetic_calls": 0,
        "recorded_calls": 0,
        "synthetic_comparisons": 0,
        "recorded_comparisons": 0,
    }


def test_eval_results_belong_to_their_run_and_comparisons_need_both_runs():
    store = _mongo()
    store.insert_run(_run("run_1"), [_result("run_1", "zeta"), _result("run_1", "alpha")])
    results = store.get_results("run_1")
    assert [row["test_id"] for row in results] == ["alpha", "zeta"]
    assert {row["run_id"] for row in results} == {"run_1"}
    assert results[0]["scorers"][0]["type"] == "exact"
    assert store.get_results("missing") == []

    stored = list(store.db["eval_results"].find({"run_id": "run_1"}))
    assert stored
    assert {doc["run_id"] for doc in stored} == {"run_1"}
    assert "scorer_details_json" not in stored[0]
    assert store.db["eval_runs"].find_one({"_id": "run_1"})["model"] == "llama-3.1-8b-instant"

    store.insert_run(_run("run_1"), [_result("run_1", "alpha")])
    assert [row["test_id"] for row in store.get_results("run_1")] == ["alpha"]
    with pytest.raises(ValueError, match="belongs to run"):
        store.insert_run(_run("run_2"), [_result("run_1", "alpha")])
    assert [row["test_id"] for row in store.get_results("run_1")] == ["alpha"]
    assert store.get_results("run_2") == []

    with pytest.raises(ValueError, match="unknown run"):
        store.insert_comparison(_comparison("missing", "run_1", comparison_id="cmp_bad"))
    assert store.get_comparison("cmp_bad") is None
    assert store.list_comparisons() == []

    store.insert_run(_run("run_2"), [_result("run_2", "alpha")])
    store.insert_comparison(_comparison("run_1", "run_2"))
    saved = store.get_comparison("cmp_test")
    assert saved["id"] == "cmp_test"
    assert saved["synthetic"] is False
    assert saved["failed_gate"] is False
    card = store.list_comparisons()[0]
    assert card["id"] == "cmp_test"
    assert card["run_a_id"] == "run_1"
    assert card["run_b_id"] == "run_2"
    assert card["suite_name"] == "customer_support"
    raw = store.db["eval_comparisons"].find_one({"_id": "cmp_test"})
    assert isinstance(raw["summary"], dict)
    assert raw["run_a_id"] == "run_1"
    assert raw["run_b_id"] == "run_2"

    counts = store.counts()
    assert counts["recorded_comparisons"] == 1
    assert counts["synthetic_comparisons"] == 0


def test_sqlite_comparison_also_requires_both_runs(tmp_path):
    store = Store(tmp_path / "t.db")
    store.migrate()
    store.insert_run(_run("run_1"), [_result("run_1", "alpha")])
    with pytest.raises(ValueError, match="unknown run"):
        store.insert_comparison(_comparison("run_1", "missing"))
    assert store.list_comparisons() == []
    store.insert_run(_run("run_2"), [_result("run_2", "alpha")])
    store.insert_comparison(_comparison("run_1", "run_2"))
    card = store.list_comparisons()[0]
    assert card["run_a_id"] == "run_1"
    assert card["run_b_id"] == "run_2"


def _gate(store, model_b: str, *, comparison_id: str, run_a_id: str, run_b_id: str) -> dict:
    suite, fingerprint = load_suite(SUITE)
    fixtures = load_fixtures(FIXTURES)
    complete = fixture_completion_fn(fixtures, simulate=True, seed=1)
    shared = dict(
        complete_fn=complete,
        store=store,
        created_at="2026-11-07T18:00:00Z",
        synthetic=True,
        fingerprint=fingerprint,
        provenance="scripted-fixture",
    )
    run_a = run_suite(suite, model="llama-3.1-8b-instant", run_id=run_a_id, label="baseline", **shared)
    run_b = run_suite(suite, model=model_b, run_id=run_b_id, label="candidate", **shared)
    return compare_runs(
        run_a,
        run_b,
        store=store,
        comparison_id=comparison_id,
        created_at="2026-11-07T18:00:00Z",
        name="mongo gate",
        gate_fail_on_pass_flip=True,
        gate_fail_on_significant_regression=True,
        n_boot=400,
        seed=1,
    )


def test_regression_gate_persists_on_mongodb():
    store = _mongo()
    regressed = _gate(
        store,
        "llama-3.2-3b-preview",
        comparison_id="cmp_3b",
        run_a_id="run_base_3b",
        run_b_id="run_cut_3b",
    )
    assert regressed["pass_flips"] >= 1
    assert regressed["significant_regression"]
    assert regressed["failed_gate"] is True
    saved = store.get_comparison("cmp_3b")
    assert saved["failed_gate"] is True
    assert saved["run_a_id"] == "run_base_3b"
    assert saved["run_b_id"] == "run_cut_3b"
    assert {row["run_id"] for row in store.get_results("run_cut_3b")} == {"run_cut_3b"}

    improved = _gate(
        store,
        "llama-3.3-70b-versatile",
        comparison_id="cmp_70b",
        run_a_id="run_base_70b",
        run_b_id="run_big_70b",
    )
    assert improved["pass_flips"] == 0
    assert improved["significant_improvement"]
    assert improved["failed_gate"] is False
    ids = {card["id"] for card in store.list_comparisons()}
    assert ids == {"cmp_3b", "cmp_70b"}
    assert store.counts()["synthetic_comparisons"] == 2


def test_cli_regression_gate_uses_mongodb(monkeypatch, tmp_path):
    client = mongomock.MongoClient()
    _use_mongomock(monkeypatch, client)
    code = main(
        [
            "eval",
            "run",
            "--model-a",
            "llama-3.1-8b-instant",
            "--model-b",
            "llama-3.2-3b-preview",
            "--db",
            str(tmp_path / "cli.db"),
            "--n-boot",
            "200",
            "--json",
        ]
    )
    assert code == 1
    assert not (tmp_path / "cli.db").exists()
    saved = client["llmwatch"]["eval_comparisons"].find_one()
    assert saved["summary"]["failed_gate"] is True
    runs = {doc["_id"] for doc in client["llmwatch"]["eval_runs"].find()}
    assert saved["run_a_id"] in runs
    assert saved["run_b_id"] in runs
    result_runs = {doc["run_id"] for doc in client["llmwatch"]["eval_results"].find()}
    assert result_runs == runs


def test_api_and_client_use_mongodb_without_a_sqlite_file(monkeypatch, tmp_path):
    client = mongomock.MongoClient()
    _use_mongomock(monkeypatch, client)
    app = create_app(tmp_path / "ignored.db", seed=False)
    store = open_store(client=client)
    store.insert_call(sample_call())
    store.insert_run(_run("run_1"), [_result("run_1", "alpha")])
    store.insert_comparison(_comparison("run_1", "run_1"))

    api = TestClient(app)
    listed = api.get("/api/calls", params={"q": "hi"}).json()
    assert listed["total"] == 1
    assert api.get("/api/calls/call_test").json()["messages"][0]["content"] == "Hi"
    assert api.get("/api/models").json()["models"] == ["llama-3.1-8b-instant"]
    cards = api.get("/api/evals/comparisons").json()["comparisons"]
    assert cards[0]["run_a_id"] == "run_1"
    meta = api.get("/api/meta").json()
    assert meta["recorded_calls"] == 1
    assert "mongodb" not in json.dumps(meta).lower()
    assert not (tmp_path / "ignored.db").exists()

    def handler(_request: httpx.Request) -> httpx.Response:
        body = {
            "id": "chatcmpl_test",
            "model": "llama-3.1-8b-instant",
            "choices": [{"message": {"role": "assistant", "content": "pong"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
        }
        return httpx.Response(200, json=body)

    db_path = tmp_path / "client.db"
    watch = WatchClient(
        base_url="https://example.test/v1",
        api_key="secret-key",
        db_path=db_path,
        provider="groq",
        transport=httpx.MockTransport(handler),
    )
    watch.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": "ping"}],
    )
    watch.close()
    assert not db_path.exists()
    recorded = client["llmwatch"]["calls"].find_one({"response_text": "pong"})
    assert recorded is not None
    assert recorded["prompt"][0]["content"] == "ping"
    assert "secret-key" not in json.dumps(recorded)
    assert "prompt_json" not in recorded
