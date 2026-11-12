"""MongoDB ledger. Same methods as ``Store``, nested documents instead of JSON text.

Collections (the ``_id`` is the string ``new_id`` already uses, not an ObjectId):

- ``calls`` — one document per LLM call
- ``eval_runs`` — one document per suite run
- ``eval_results`` — one document per scored test; ``run_id`` is the run ``_id``
- ``eval_comparisons`` — one document per gate result; ``run_a_id`` and ``run_b_id``
  are run ``_id`` values

A result is written only after its run document exists, and every result row
uses that run's id. A comparison is rejected when either run is missing.
SQLite enforces the result foreign key in the schema and the same comparison
check in ``Store.insert_comparison``.
"""

from __future__ import annotations

import json
from typing import Any

from llmwatch.store import (
    _comparison_card,
    _dump,
    _result_to_dict,
    call_record,
    call_to_dict,
    ensure_comparison_runs,
)

CALLS = "calls"
EVAL_RUNS = "eval_runs"
EVAL_RESULTS = "eval_results"
EVAL_COMPARISONS = "eval_comparisons"


def connect_mongo(uri: str) -> Any:
    """Open a real client. Tests pass their own client and never call this."""

    try:
        from pymongo import MongoClient
    except ImportError as exc:
        raise RuntimeError(
            "LLMWATCH_MONGODB_URI is set but pymongo is not installed. "
            'Install the MongoDB extra: pip install "llm-watch[mongodb]"'
        ) from exc
    return MongoClient(uri)


class MongoStore:
    """Document ledger selected by ``LLMWATCH_MONGODB_URI``."""

    def __init__(self, uri: str, *, database: str = "llmwatch", client: Any = None):
        cleaned = (uri or "").strip()
        if not cleaned:
            raise ValueError("MongoDB URI is empty")
        self.uri = cleaned
        self.database_name = (database or "").strip() or "llmwatch"
        self.client = client if client is not None else connect_mongo(cleaned)
        self.db = self.client[self.database_name]

    def migrate(self) -> None:
        self.db[CALLS].create_index("created_at")
        self.db[CALLS].create_index("model")
        self.db[CALLS].create_index("status")
        self.db[CALLS].create_index([("created_at", -1), ("_id", -1)])
        self.db[EVAL_RUNS].create_index("created_at")
        self.db[EVAL_RESULTS].create_index("run_id")
        self.db[EVAL_RESULTS].create_index([("run_id", 1), ("test_id", 1)])
        self.db[EVAL_COMPARISONS].create_index([("created_at", -1), ("_id", -1)])

    def clear(self) -> None:
        self.db[EVAL_RESULTS].delete_many({})
        self.db[EVAL_COMPARISONS].delete_many({})
        self.db[EVAL_RUNS].delete_many({})
        self.db[CALLS].delete_many({})

    def insert_call(self, row: dict[str, Any]) -> str:
        record = call_record(row)
        raw_response = _dump(record["response"])
        document = {
            "_id": record["id"],
            "created_at": record["created_at"],
            "provider": record["provider"],
            "model": record["model"],
            "endpoint": record["endpoint"],
            "prompt": _json_clone(record["prompt"], allow_nan=True),
            "response": None if raw_response is None else json.loads(raw_response),
            "response_text": record["response_text"],
            "prompt_tokens": record["prompt_tokens"],
            "completion_tokens": record["completion_tokens"],
            "total_tokens": record["total_tokens"],
            "token_source": record["token_source"],
            "latency_ms": record["latency_ms"],
            "cost_usd": record["cost_usd"],
            "price_source": record["price_source"],
            "status": record["status"],
            "error_type": record["error_type"],
            "error_message": record["error_message"],
            "http_status": record["http_status"],
            "attempts": record["attempts"],
            "synthetic": record["synthetic"],
            "metadata": _json_clone(record["metadata"], allow_nan=True),
            "streaming": record["streaming"],
        }
        self.db[CALLS].replace_one({"_id": record["id"]}, document, upsert=True)
        return record["id"]

    def get_call(self, call_id: str) -> dict[str, Any] | None:
        document = self.db[CALLS].find_one({"_id": call_id})
        if document is None:
            return None
        return call_to_dict(_call_row(document), detail=True)

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
        # Substring search matches SQLite LIKE: ASCII case-insensitive, and
        # "%" / "_" are literal characters. Filter before pagination.
        query = _call_query(model=model, status=status, since=since, until=until)
        limit = max(1, min(int(limit), 100))
        offset = max(0, int(offset))
        order = [("created_at", -1), ("_id", -1)]
        if q:
            matched = [doc for doc in self.db[CALLS].find(query).sort(order) if _matches_q(doc, q)]
            total = len(matched)
            page = matched[offset : offset + limit]
        else:
            total = int(self.db[CALLS].count_documents(query))
            page = list(self.db[CALLS].find(query).sort(order).skip(offset).limit(limit))
        return total, [call_to_dict(_call_row(doc), detail=False) for doc in page]

    def distinct_models(self) -> list[str]:
        names = [name for name in self.db[CALLS].distinct("model") if name is not None]
        return sorted(names)

    def call_metrics(self) -> list[dict[str, Any]]:
        rows = []
        for doc in self.db[CALLS].find({}):
            rows.append(
                {
                    "created_at": doc.get("created_at"),
                    "model": doc.get("model"),
                    "status": doc.get("status"),
                    "latency_ms": doc.get("latency_ms"),
                    "cost_usd": doc.get("cost_usd"),
                    "prompt_tokens": doc.get("prompt_tokens"),
                    "completion_tokens": doc.get("completion_tokens"),
                    "synthetic": 1 if doc.get("synthetic") else 0,
                }
            )
        return rows

    def counts(self) -> dict[str, int]:
        synthetic_calls, recorded_calls = _count_synthetic(self.db[CALLS])
        synthetic_comparisons, recorded_comparisons = _count_synthetic(self.db[EVAL_COMPARISONS])
        return {
            "synthetic_calls": synthetic_calls,
            "recorded_calls": recorded_calls,
            "synthetic_comparisons": synthetic_comparisons,
            "recorded_comparisons": recorded_comparisons,
        }

    def count_calls(self) -> int:
        return int(self.db[CALLS].count_documents({}))

    def call_search_index(self) -> dict[str, dict[str, str]]:
        rows = self.db[CALLS].find({}, {"prompt": 1, "response_text": 1}).sort("_id", 1)
        return {
            doc["_id"]: {
                "prompt_json": json.dumps(doc.get("prompt") or [], ensure_ascii=False),
                "response_text": doc.get("response_text") or "",
            }
            for doc in rows
        }

    def insert_run(self, row: dict[str, Any], results: list[dict[str, Any]]) -> str:
        run_id = row["id"]
        document = {
            "_id": run_id,
            "created_at": row["created_at"],
            "suite_name": row["suite_name"],
            "suite_fingerprint": row.get("suite_fingerprint"),
            "model": row["model"],
            "label": row.get("label"),
            "synthetic": bool(row.get("synthetic")),
            "provenance": row.get("provenance"),
            "mean_score": row.get("mean_score"),
            "pass_rate": row.get("pass_rate"),
            "n_tests": row.get("n_tests"),
            "summary": _json_clone(row.get("summary") or {}),
        }
        self.db[EVAL_RUNS].replace_one({"_id": run_id}, document, upsert=True)
        if self.db[EVAL_RUNS].find_one({"_id": run_id}, {"_id": 1}) is None:
            raise ValueError(f"eval run {run_id} was not stored")
        new_ids: list[str] = []
        for result in results:
            result_doc = _result_document(run_id, result)
            existing = self.db[EVAL_RESULTS].find_one({"_id": result_doc["_id"]}, {"run_id": 1})
            if existing is not None and existing.get("run_id") != run_id:
                raise ValueError(
                    f"eval result {result_doc['_id']} belongs to run {existing.get('run_id')}"
                )
            new_ids.append(result_doc["_id"])
            self.db[EVAL_RESULTS].replace_one({"_id": result_doc["_id"]}, result_doc, upsert=True)
        self.db[EVAL_RESULTS].delete_many({"run_id": run_id, "_id": {"$nin": new_ids}})
        return run_id

    def get_results(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.db[EVAL_RESULTS].find({"run_id": run_id}).sort("test_id", 1)
        return [_result_to_dict(_result_row(doc)) for doc in rows]

    def insert_comparison(self, row: dict[str, Any]) -> str:
        summary = _json_clone(row["summary"])
        ensure_comparison_runs(
            lambda run_id: self.db[EVAL_RUNS].find_one({"_id": run_id}, {"_id": 1}) is not None,
            row["run_a_id"],
            row["run_b_id"],
        )
        document = {
            "_id": row["id"],
            "created_at": row["created_at"],
            "suite_name": row["suite_name"],
            "run_a_id": row["run_a_id"],
            "run_b_id": row["run_b_id"],
            "synthetic": bool(row.get("synthetic")),
            "significant_regression": bool(
                summary.get("significant_regression") or summary.get("failed_gate")
            ),
            "summary": summary,
        }
        self.db[EVAL_COMPARISONS].replace_one({"_id": row["id"]}, document, upsert=True)
        return row["id"]

    def list_comparisons(self) -> list[dict[str, Any]]:
        rows = self.db[EVAL_COMPARISONS].find().sort([("created_at", -1), ("_id", -1)])
        return [_comparison_card(_comparison_row(doc)) for doc in rows]

    def get_comparison(self, comparison_id: str) -> dict[str, Any] | None:
        document = self.db[EVAL_COMPARISONS].find_one({"_id": comparison_id})
        if document is None:
            return None
        summary = json.loads(_comparison_row(document)["summary_json"])
        summary["id"] = document["_id"]
        summary["synthetic"] = bool(document.get("synthetic"))
        return summary


def _json_clone(value: Any, *, allow_nan: bool = False) -> Any:
    if value is None:
        return None
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=allow_nan))


def _call_query(
    *,
    model: str | None,
    status: str | None,
    since: str | None,
    until: str | None,
) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if model:
        query["model"] = model
    if status:
        query["status"] = status
    created: dict[str, str] = {}
    if since:
        created["$gte"] = since
    if until:
        created["$lte"] = until
    if created:
        query["created_at"] = created
    return query


def _matches_q(document: dict[str, Any], q: str) -> bool:
    folded = q.lower()
    haystacks = (
        json.dumps(document.get("prompt") or [], ensure_ascii=False),
        document.get("response_text") or "",
        document.get("model") or "",
    )
    return any(folded in haystack.lower() for haystack in haystacks)


def _call_row(document: dict[str, Any]) -> dict[str, Any]:
    response = document.get("response")
    response_json = None
    if response is not None:
        response_json = json.dumps(response, ensure_ascii=False, allow_nan=False)
    return {
        "id": document["_id"],
        "created_at": document.get("created_at"),
        "provider": document.get("provider"),
        "model": document.get("model"),
        "endpoint": document.get("endpoint"),
        "prompt_json": json.dumps(document.get("prompt") or [], ensure_ascii=False),
        "response_json": response_json,
        "response_text": document.get("response_text") or "",
        "prompt_tokens": document.get("prompt_tokens"),
        "completion_tokens": document.get("completion_tokens"),
        "total_tokens": document.get("total_tokens"),
        "token_source": document.get("token_source"),
        "latency_ms": document.get("latency_ms"),
        "cost_usd": document.get("cost_usd"),
        "price_source": document.get("price_source"),
        "status": document.get("status"),
        "error_type": document.get("error_type"),
        "error_message": document.get("error_message"),
        "http_status": document.get("http_status"),
        "attempts": document.get("attempts"),
        "synthetic": 1 if document.get("synthetic") else 0,
        "metadata_json": json.dumps(document.get("metadata") or {}, ensure_ascii=False),
        "streaming": 1 if document.get("streaming") else 0,
    }


def _result_document(run_id: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "_id": result["id"],
        "run_id": run_id,
        "test_id": result["test_id"],
        "description": result.get("description") or "",
        "prompt": result["prompt"],
        "output": result.get("output") or "",
        "score": result["score"],
        "passed": bool(result["passed"]),
        "scorers": _json_clone(result.get("scorers") or []),
        "latency_ms": result.get("latency_ms"),
        "cost_usd": result.get("cost_usd"),
        "prompt_tokens": result.get("prompt_tokens"),
        "completion_tokens": result.get("completion_tokens"),
        "metrics_simulated": bool(result.get("metrics_simulated")),
        "error": result.get("error"),
    }


def _result_row(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": document["_id"],
        "run_id": document["run_id"],
        "test_id": document.get("test_id"),
        "description": document.get("description"),
        "prompt": document.get("prompt"),
        "output": document.get("output"),
        "score": document.get("score"),
        "passed": 1 if document.get("passed") else 0,
        "scorer_details_json": json.dumps(document.get("scorers") or [], allow_nan=False),
        "latency_ms": document.get("latency_ms"),
        "cost_usd": document.get("cost_usd"),
        "prompt_tokens": document.get("prompt_tokens"),
        "completion_tokens": document.get("completion_tokens"),
        "metrics_simulated": 1 if document.get("metrics_simulated") else 0,
        "error": document.get("error"),
    }


def _comparison_row(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": document["_id"],
        "created_at": document.get("created_at"),
        "suite_name": document.get("suite_name"),
        "run_a_id": document.get("run_a_id"),
        "run_b_id": document.get("run_b_id"),
        "synthetic": 1 if document.get("synthetic") else 0,
        "summary_json": json.dumps(document.get("summary") or {}, allow_nan=False),
    }


def _count_synthetic(collection: Any) -> tuple[int, int]:
    synthetic = int(collection.count_documents({"synthetic": True}))
    recorded = int(collection.count_documents({"synthetic": False}))
    return synthetic, recorded
