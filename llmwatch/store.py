"""SQLite ledger for calls, eval runs, and comparisons."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from llmwatch.text import new_id, preview, user_text

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    endpoint TEXT,
    prompt_json TEXT NOT NULL,
    response_json TEXT,
    response_text TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    token_source TEXT,
    latency_ms REAL,
    cost_usd REAL,
    price_source TEXT,
    status TEXT NOT NULL,
    error_type TEXT,
    error_message TEXT,
    http_status INTEGER,
    attempts INTEGER NOT NULL DEFAULT 1,
    synthetic INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT,
    streaming INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_calls_created ON calls(created_at);
CREATE INDEX IF NOT EXISTS idx_calls_model ON calls(model);
CREATE INDEX IF NOT EXISTS idx_calls_status ON calls(status);

CREATE TABLE IF NOT EXISTS eval_runs (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    suite_name TEXT NOT NULL,
    suite_fingerprint TEXT,
    model TEXT NOT NULL,
    label TEXT,
    synthetic INTEGER NOT NULL DEFAULT 0,
    provenance TEXT,
    mean_score REAL,
    pass_rate REAL,
    n_tests INTEGER,
    summary_json TEXT
);

CREATE TABLE IF NOT EXISTS eval_results (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    test_id TEXT NOT NULL,
    description TEXT,
    prompt TEXT NOT NULL,
    output TEXT,
    score REAL,
    passed INTEGER,
    scorer_details_json TEXT,
    latency_ms REAL,
    cost_usd REAL,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    metrics_simulated INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    FOREIGN KEY(run_id) REFERENCES eval_runs(id)
);

CREATE TABLE IF NOT EXISTS eval_comparisons (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    suite_name TEXT NOT NULL,
    run_a_id TEXT NOT NULL,
    run_b_id TEXT NOT NULL,
    synthetic INTEGER NOT NULL DEFAULT 0,
    significant_regression INTEGER NOT NULL,
    summary_json TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
            conn.commit()
        finally:
            conn.close()

    def migrate(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            conn.execute("PRAGMA journal_mode=WAL")

    def clear(self) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM eval_results")
            conn.execute("DELETE FROM eval_comparisons")
            conn.execute("DELETE FROM eval_runs")
            conn.execute("DELETE FROM calls")

    def insert_call(self, row: dict[str, Any]) -> str:
        call_id = row.get("id") or new_id("call")
        payload = {
            "id": call_id,
            "created_at": row["created_at"],
            "provider": row.get("provider") or "openai-compatible",
            "model": row["model"],
            "endpoint": row.get("endpoint") or "/v1/chat/completions",
            "prompt_json": json.dumps(row.get("prompt") or [], ensure_ascii=False),
            "response_json": _dump(row.get("response")),
            "response_text": row.get("response_text") or "",
            "prompt_tokens": int(row.get("prompt_tokens") or 0),
            "completion_tokens": int(row.get("completion_tokens") or 0),
            "total_tokens": int(row.get("total_tokens") or 0),
            "token_source": row.get("token_source") or "unknown",
            "latency_ms": float(row.get("latency_ms") or 0),
            "cost_usd": float(row.get("cost_usd") or 0),
            "price_source": row.get("price_source") or "default",
            "status": row["status"],
            "error_type": row.get("error_type"),
            "error_message": row.get("error_message"),
            "http_status": row.get("http_status"),
            "attempts": int(row.get("attempts") or 1),
            "synthetic": 1 if row.get("synthetic") else 0,
            "metadata_json": json.dumps(row.get("metadata") or {}, ensure_ascii=False),
            "streaming": 1 if row.get("streaming") else 0,
        }
        columns = ", ".join(payload)
        placeholders = ", ".join(f":{name}" for name in payload)
        with self.connect() as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO calls ({columns}) VALUES ({placeholders})",
                payload,
            )
        return call_id

    def get_call(self, call_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone()
        if row is None:
            return None
        return call_to_dict(row, detail=True)

    def list_calls(
        self,
        *,
        model: str | None = None,
        status: str | None = None,
        q: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> tuple[int, list[dict[str, Any]]]:
        where, params = _call_filters(model=model, status=status, q=q, since=since, until=until)
        limit = max(1, min(int(limit), 100))
        offset = max(0, int(offset))
        with self.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) AS n FROM calls {where}", params).fetchone()["n"]
            rows = conn.execute(
                f"SELECT * FROM calls {where} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
        return int(total), [call_to_dict(row, detail=False) for row in rows]

    def distinct_models(self) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute("SELECT DISTINCT model FROM calls ORDER BY model").fetchall()
        return [row["model"] for row in rows]

    def call_metrics(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT created_at, model, status, latency_ms, cost_usd,
                       prompt_tokens, completion_tokens, synthetic
                FROM calls
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def counts(self) -> dict[str, int]:
        with self.connect() as conn:
            calls = conn.execute(
                "SELECT synthetic, COUNT(*) AS n FROM calls GROUP BY synthetic"
            ).fetchall()
            comparisons = conn.execute(
                "SELECT synthetic, COUNT(*) AS n FROM eval_comparisons GROUP BY synthetic"
            ).fetchall()
        out = {
            "synthetic_calls": 0,
            "recorded_calls": 0,
            "synthetic_comparisons": 0,
            "recorded_comparisons": 0,
        }
        for row in calls:
            key = "synthetic_calls" if row["synthetic"] else "recorded_calls"
            out[key] = int(row["n"])
        for row in comparisons:
            key = "synthetic_comparisons" if row["synthetic"] else "recorded_comparisons"
            out[key] = int(row["n"])
        return out

    def count_calls(self) -> int:
        with self.connect() as conn:
            return int(conn.execute("SELECT COUNT(*) AS n FROM calls").fetchone()["n"])

    def insert_run(self, row: dict[str, Any], results: list[dict[str, Any]]) -> str:
        run_id = row["id"]
        with self.connect() as conn:
            conn.execute("DELETE FROM eval_results WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM eval_runs WHERE id = ?", (run_id,))
            conn.execute(
                """
                INSERT INTO eval_runs (
                    id, created_at, suite_name, suite_fingerprint, model, label,
                    synthetic, provenance, mean_score, pass_rate, n_tests, summary_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    row["created_at"],
                    row["suite_name"],
                    row.get("suite_fingerprint"),
                    row["model"],
                    row.get("label"),
                    1 if row.get("synthetic") else 0,
                    row.get("provenance"),
                    row.get("mean_score"),
                    row.get("pass_rate"),
                    row.get("n_tests"),
                    json.dumps(row.get("summary") or {}, allow_nan=False),
                ),
            )
            for result in results:
                conn.execute(
                    """
                    INSERT INTO eval_results (
                        id, run_id, test_id, description, prompt, output, score, passed,
                        scorer_details_json, latency_ms, cost_usd, prompt_tokens,
                        completion_tokens, metrics_simulated, error
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result["id"],
                        run_id,
                        result["test_id"],
                        result.get("description") or "",
                        result["prompt"],
                        result.get("output") or "",
                        result["score"],
                        1 if result["passed"] else 0,
                        json.dumps(result.get("scorers") or [], allow_nan=False),
                        result.get("latency_ms"),
                        result.get("cost_usd"),
                        result.get("prompt_tokens"),
                        result.get("completion_tokens"),
                        1 if result.get("metrics_simulated") else 0,
                        result.get("error"),
                    ),
                )
        return run_id

    def get_results(self, run_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM eval_results WHERE run_id = ? ORDER BY test_id",
                (run_id,),
            ).fetchall()
        return [_result_to_dict(row) for row in rows]

    def insert_comparison(self, row: dict[str, Any]) -> str:
        summary = row["summary"]
        with self.connect() as conn:
            conn.execute("DELETE FROM eval_comparisons WHERE id = ?", (row["id"],))
            conn.execute(
                """
                INSERT INTO eval_comparisons (
                    id, created_at, suite_name, run_a_id, run_b_id, synthetic,
                    significant_regression, summary_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["created_at"],
                    row["suite_name"],
                    row["run_a_id"],
                    row["run_b_id"],
                    1 if row.get("synthetic") else 0,
                    1 if summary.get("significant_regression") or summary.get("failed_gate") else 0,
                    json.dumps(summary, allow_nan=False),
                ),
            )
        return row["id"]

    def list_comparisons(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM eval_comparisons ORDER BY created_at DESC, id DESC"
            ).fetchall()
        return [_comparison_card(row) for row in rows]

    def get_comparison(self, comparison_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM eval_comparisons WHERE id = ?",
                (comparison_id,),
            ).fetchone()
        if row is None:
            return None
        summary = json.loads(row["summary_json"])
        summary["id"] = row["id"]
        summary["synthetic"] = bool(row["synthetic"])
        return summary


def call_to_dict(row: sqlite3.Row, *, detail: bool) -> dict[str, Any]:
    messages = json.loads(row["prompt_json"])
    metadata = json.loads(row["metadata_json"] or "{}")
    synthetic = bool(row["synthetic"])
    data: dict[str, Any] = {
        "id": row["id"],
        "created_at": row["created_at"],
        "provider": row["provider"],
        "model": row["model"],
        "endpoint": row["endpoint"],
        "prompt_preview": preview(user_text(messages)),
        "response_preview": preview(row["response_text"] or ""),
        "prompt_tokens": row["prompt_tokens"],
        "completion_tokens": row["completion_tokens"],
        "total_tokens": row["total_tokens"],
        "token_source": row["token_source"],
        "latency_ms": row["latency_ms"],
        "cost_usd": row["cost_usd"],
        "price_source": row["price_source"],
        "status": row["status"],
        "error_type": row["error_type"],
        "error_message": row["error_message"],
        "http_status": row["http_status"],
        "attempts": row["attempts"],
        "synthetic": synthetic,
        "data_label": "synthetic demo" if synthetic else "recorded",
        "streaming": bool(row["streaming"]),
        "route": metadata.get("route"),
        "metadata": metadata,
    }
    if detail:
        data["messages"] = messages
        data["response_text"] = row["response_text"] or ""
        data["response"] = json.loads(row["response_json"]) if row["response_json"] else None
    return data


def _result_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "test_id": row["test_id"],
        "description": row["description"],
        "prompt": row["prompt"],
        "output": row["output"],
        "score": row["score"],
        "passed": bool(row["passed"]),
        "scorers": json.loads(row["scorer_details_json"] or "[]"),
        "latency_ms": row["latency_ms"],
        "cost_usd": row["cost_usd"],
        "prompt_tokens": row["prompt_tokens"],
        "completion_tokens": row["completion_tokens"],
        "metrics_simulated": bool(row["metrics_simulated"]),
        "error": row["error"],
    }


def _comparison_card(row: sqlite3.Row) -> dict[str, Any]:
    summary = json.loads(row["summary_json"])
    keep = (
        "name",
        "model_a",
        "model_b",
        "label_a",
        "label_b",
        "mean_a",
        "mean_b",
        "delta",
        "ci_low",
        "ci_high",
        "significant_regression",
        "significant_improvement",
        "pass_rate_a",
        "pass_rate_b",
        "pass_flips",
        "failed_gate",
        "provenance",
        "narrative",
        "n_tests",
    )
    card = {key: summary.get(key) for key in keep}
    card.update(
        {
            "id": row["id"],
            "created_at": row["created_at"],
            "suite_name": row["suite_name"],
            "run_a_id": row["run_a_id"],
            "run_b_id": row["run_b_id"],
            "synthetic": bool(row["synthetic"]),
        }
    )
    return card


def _call_filters(
    *,
    model: str | None,
    status: str | None,
    q: str | None,
    since: str | None,
    until: str | None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if model:
        clauses.append("model = ?")
        params.append(model)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if since:
        clauses.append("created_at >= ?")
        params.append(since)
    if until:
        clauses.append("created_at <= ?")
        params.append(until)
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        clauses.append(
            "(prompt_json LIKE ? ESCAPE '\\' OR IFNULL(response_text, '') LIKE ? ESCAPE '\\' OR model LIKE ? ESCAPE '\\')"
        )
        like = f"%{escaped}%"
        params.extend([like, like, like])
    if not clauses:
        return "", params
    return "WHERE " + " AND ".join(clauses), params


def _dump(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, allow_nan=False)
