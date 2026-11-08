"""Export the dashboard's API responses for the static demo.

The files are the seeded ledger: simulated calls from ``seed_demo`` plus the
eval comparisons the real runner writes. ``filter_calls`` matches
``Store.list_calls`` (model, status, time window, and a case-insensitive
substring on the stored prompt JSON, response text, and model, with ``%`` and
``_`` treated as literals). Keep it aligned with
``dashboard/src/lib/staticDemo.ts``.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from llmwatch.api.main import create_app
from llmwatch.seed import seed_demo
from llmwatch.store import Store

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def export_demo(out_dir: str | Path, db_path: str | Path | None = None) -> dict:
    """Write dashboard JSON into ``out_dir``.

    With no database, seed a temporary demo ledger. With a database, seed it
    only when it is empty, then export whatever is stored.
    """

    out = Path(out_dir)
    if db_path is None:
        with tempfile.TemporaryDirectory(prefix="llmwatch-demo-") as tmp:
            db = Path(tmp) / "demo.db"
            seed_demo(db)
            return _export(db, out)
    path = Path(db_path)
    seed_demo(path, force=False)
    return _export(path, out)


def filter_calls(
    calls: list[dict],
    search: dict[str, dict[str, str]],
    *,
    model: str | None = None,
    status: str | None = None,
    q: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> dict:
    """Apply the calls-list query to an exported catalog."""

    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))
    selected: list[dict] = []
    for call in calls:
        if model and call["model"] != model:
            continue
        if status and call["status"] != status:
            continue
        if since and call["created_at"] < since:
            continue
        if until and call["created_at"] > until:
            continue
        if q:
            blob = search[call["id"]]
            haystacks = (
                blob.get("prompt_json") or "",
                blob.get("response_text") or "",
                call.get("model") or "",
            )
            folded = q.lower()
            if not any(folded in haystack.lower() for haystack in haystacks):
                continue
        selected.append(call)
    return {
        "total": len(selected),
        "limit": limit,
        "offset": offset,
        "calls": selected[offset : offset + limit],
    }


def search_index(store: Store) -> dict[str, dict[str, str]]:
    """Columns the calls query searches, keyed by call id."""

    with store.connect() as conn:
        rows = conn.execute(
            "SELECT id, prompt_json, response_text FROM calls ORDER BY id"
        ).fetchall()
    return {
        row["id"]: {
            "prompt_json": row["prompt_json"],
            "response_text": row["response_text"] or "",
        }
        for row in rows
    }


def _export(db_path: Path, out: Path) -> dict:
    _prepare(out)
    store = Store(db_path)
    app = create_app(db_path, seed=False)
    with TestClient(app) as client:
        meta = _get(client, "/api/meta")
        models = _get(client, "/api/models")
        summary = _get(client, "/api/metrics/summary")
        timeseries = _get(client, "/api/metrics/timeseries")
        comparisons = _get(client, "/api/evals/comparisons")
        calls = _paged_calls(client)
        _write(out / "meta.json", meta)
        _write(out / "models.json", models)
        _write(out / "metrics" / "summary.json", summary)
        _write(out / "metrics" / "timeseries.json", timeseries)
        _write(out / "evals" / "comparisons.json", comparisons)
        _write(out / "calls.json", calls)
        _write(out / "calls-search.json", search_index(store))
        for call in calls["calls"]:
            call_id = _safe_name(call["id"])
            detail = _get(client, f"/api/calls/{call_id}")
            _write(out / "calls" / f"{call_id}.json", detail)
        comparison_ids: list[str] = []
        for card in comparisons["comparisons"]:
            comparison_id = _safe_name(card["id"])
            comparison_ids.append(comparison_id)
            detail = _get(client, f"/api/evals/comparisons/{comparison_id}")
            _write(out / "evals" / "comparisons" / f"{comparison_id}.json", detail)
    return {
        "exported": True,
        "out": str(out),
        "calls": calls["total"],
        "comparisons": comparison_ids,
    }


def _paged_calls(client: TestClient) -> dict:
    calls: list[dict] = []
    offset = 0
    total = 0
    while True:
        body = _get(client, "/api/calls", params={"limit": 100, "offset": offset})
        total = int(body["total"])
        batch = body["calls"]
        calls.extend(batch)
        if not batch or len(calls) >= total:
            break
        offset += len(batch)
    return {"total": total, "limit": total, "offset": 0, "calls": calls}


def _get(client: TestClient, path: str, params: dict | None = None) -> dict:
    response = client.get(path, params=params)
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError(f"{path} did not return an object")
    return body


def _prepare(out: Path) -> None:
    if out.exists() and not out.is_dir():
        raise ValueError(f"{out} is not a directory")
    out.mkdir(parents=True, exist_ok=True)
    for child in ("calls", "metrics", "evals"):
        path = out / child
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    for name in ("meta.json", "models.json", "calls.json", "calls-search.json"):
        file = out / name
        if file.is_file():
            file.unlink()


def _safe_name(value: str) -> str:
    if not _SAFE_ID.fullmatch(value):
        raise ValueError(f"refusing to write an unsafe id {value!r}")
    return value


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
