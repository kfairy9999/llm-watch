"""The static demo JSON is the same payload the dashboard API returns."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from llmwatch.cli import main
from llmwatch.demo_export import filter_calls
from llmwatch.seed import CALL_COUNT, seed_demo
from llmwatch.store import Store

ROOT = Path(__file__).resolve().parents[1]


def _page_calls(client: TestClient) -> tuple[int, list[dict]]:
    rows: list[dict] = []
    offset = 0
    total = 0
    while True:
        body = client.get("/api/calls", params={"limit": 100, "offset": offset}).json()
        total = body["total"]
        batch = body["calls"]
        rows.extend(batch)
        if not batch or len(rows) >= total:
            break
        offset += len(batch)
    return total, rows


def test_export_demo_matches_api_responses(tmp_path):
    db = tmp_path / "demo.db"
    out = tmp_path / "demo"
    seed_demo(db)
    assert main(["export-demo", str(out), "--db", str(db)]) == 0

    stale = out / "calls" / "call_stale.json"
    stale.write_text("{}", encoding="utf-8")
    assert main(["export-demo", str(out), "--db", str(db)]) == 0
    assert not stale.exists()

    client = TestClient(create_client_app(db))
    assert _load(out / "meta.json") == client.get("/api/meta").json()
    assert _load(out / "models.json") == client.get("/api/models").json()
    assert _load(out / "metrics" / "summary.json") == client.get("/api/metrics/summary").json()
    assert _load(out / "metrics" / "timeseries.json") == client.get("/api/metrics/timeseries").json()
    comparisons = client.get("/api/evals/comparisons").json()
    assert _load(out / "evals" / "comparisons.json") == comparisons
    for card in comparisons["comparisons"]:
        detail = client.get(f"/api/evals/comparisons/{card['id']}").json()
        assert _load(out / "evals" / "comparisons" / f"{card['id']}.json") == detail

    total, rows = _page_calls(client)
    exported_calls = _load(out / "calls.json")
    assert exported_calls["total"] == total == CALL_COUNT
    assert exported_calls["offset"] == 0
    assert exported_calls["calls"] == rows
    for row in rows:
        assert _load(out / "calls" / f"{row['id']}.json") == client.get(f"/api/calls/{row['id']}").json()

    store = Store(db)
    with store.connect() as conn:
        stored = conn.execute("SELECT id, prompt_json, response_text FROM calls ORDER BY id").fetchall()
    search = _load(out / "calls-search.json")
    assert search == {
        row["id"]: {"prompt_json": row["prompt_json"], "response_text": row["response_text"] or ""}
        for row in stored
    }

    queries = [
        {"limit": 25, "offset": 0},
        {"limit": 25, "offset": 25},
        {"model": "llama-3.1-8b-instant", "limit": 100},
        {"status": "error", "limit": 50},
        {"q": "Austin", "limit": 100},
        {"q": "austin", "limit": 25},
        {"q": "%", "limit": 25},
        {"q": "_", "limit": 25},
        {"q": "fictional", "limit": 100, "offset": 100},
        {"model": "llama-3.3-70b-versatile", "status": "ok", "q": "HX-200", "limit": 25, "offset": 0},
        {"since": "2026-11-07T00:00:00Z", "until": "2026-11-08T00:00:00Z", "limit": 25},
    ]
    for params in queries:
        api = client.get("/api/calls", params=params).json()
        local = filter_calls(exported_calls["calls"], search, **params)
        assert local == api, params
    fictional = client.get("/api/calls", params={"q": "fictional", "limit": 1}).json()
    assert fictional["total"] == CALL_COUNT


def test_export_demo_without_a_database_seeds_one(tmp_path):
    out = tmp_path / "fresh"
    assert main(["export-demo", str(out)]) == 0
    meta = _load(out / "meta.json")
    assert meta["synthetic_calls"] == CALL_COUNT
    assert meta["recorded_calls"] == 0
    assert "Synthetic demo data" in meta["disclaimer"]
    assert _load(out / "evals" / "comparisons.json")["comparisons"]


def test_static_demo_wiring():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Live demo: [https://llm-watch.kfairley9999.workers.dev](https://llm-watch.kfairley9999.workers.dev) (synthetic data, static build)" in readme
    assert "VITE_DEMO_STATIC" in readme
    assert "wrangler.jsonc" in readme
    assert "npm run build:demo" in readme
    package = json.loads((ROOT / "dashboard" / "package.json").read_text(encoding="utf-8"))
    assert "export-demo" in package["scripts"]["build:demo"]
    assert "VITE_DEMO_STATIC=1" in package["scripts"]["build:demo"]
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "npm run build:demo" in workflow
    wrangler = (ROOT / "dashboard" / "wrangler.jsonc").read_text(encoding="utf-8")
    assert '"name": "llm-watch"' in wrangler
    assert "single-page-application" in wrangler
    assert "not_found_handling" in wrangler
    assert not (ROOT / "dashboard" / "public" / "_redirects").exists()


def create_client_app(db: Path):
    from llmwatch.api.main import create_app

    return create_app(db, seed=False)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
