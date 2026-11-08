"""Aggregate the call ledger for the dashboard charts."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from llmwatch.eval.stats import quantile

MODEL_ORDER = [
    "llama-3.2-3b-preview",
    "llama-3.1-8b-instant",
    "llama-3.3-70b-versatile",
]


def summarize(rows: list[dict]) -> dict:
    ok = [row for row in rows if row["status"] == "ok"]
    errors = len(rows) - len(ok)
    latencies = [float(row["latency_ms"]) for row in ok if row["latency_ms"] is not None]
    by_model: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_model[row["model"]].append(row)
    return {
        "calls": len(rows),
        "errors": errors,
        "error_rate": (errors / len(rows)) if rows else 0.0,
        "cost_usd": sum(float(row["cost_usd"] or 0) for row in rows),
        "prompt_tokens": sum(int(row["prompt_tokens"] or 0) for row in rows),
        "completion_tokens": sum(int(row["completion_tokens"] or 0) for row in rows),
        "latency_p50_ms": _percentile(latencies, 0.5),
        "latency_p95_ms": _percentile(latencies, 0.95),
        "latency_basis": "successful calls",
        "by_model": [_model_summary(model, by_model[model]) for model in _ordered(by_model)],
    }


def timeseries(rows: list[dict]) -> dict:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        buckets[str(row["created_at"])[:10]].append(row)
    if buckets:
        start = date.fromisoformat(min(buckets))
        end = date.fromisoformat(max(buckets))
        days = []
        cursor = start
        while cursor <= end:
            days.append(cursor.isoformat())
            cursor += timedelta(days=1)
    else:
        days = []
    models = _ordered({row["model"] for row in rows})
    points = []
    for day in days:
        group = buckets.get(day, [])
        by_model = defaultdict(list)
        for row in group:
            by_model[row["model"]].append(row)
        points.append(
            {
                "date": day,
                "calls": len(group),
                "errors": sum(1 for row in group if row["status"] != "ok"),
                "cost_usd": sum(float(row["cost_usd"] or 0) for row in group),
                "tokens": sum(int(row["prompt_tokens"] or 0) + int(row["completion_tokens"] or 0) for row in group),
                "latency_p50_ms": _percentile(
                    [float(row["latency_ms"]) for row in group if row["status"] == "ok"],
                    0.5,
                ),
                "by_model": {
                    model: _point_model(by_model[model]) for model in models if by_model[model]
                },
            }
        )
    synthetic_rows = sum(1 for row in rows if row["synthetic"])
    if not rows:
        label = "empty"
    elif synthetic_rows == len(rows):
        label = "synthetic"
    elif synthetic_rows == 0:
        label = "recorded"
    else:
        label = "mixed"
    return {
        "bucket": "day",
        "data_label": label,
        "synthetic": label == "synthetic",
        "models": models,
        "total_calls": len(rows),
        "points": points,
    }


def _model_summary(model: str, rows: list[dict]) -> dict:
    ok = [row for row in rows if row["status"] == "ok"]
    cost = sum(float(row["cost_usd"] or 0) for row in rows)
    count = len(rows) or 1
    return {
        "model": model,
        "calls": len(rows),
        "errors": len(rows) - len(ok),
        "error_rate": (len(rows) - len(ok)) / len(rows) if rows else 0.0,
        "cost_usd": cost,
        "mean_cost_per_1k": (cost / len(rows)) * 1000 if rows else 0.0,
        "tokens": sum(int(row["prompt_tokens"] or 0) + int(row["completion_tokens"] or 0) for row in rows),
        "latency_p50_ms": _percentile([float(row["latency_ms"]) for row in ok], 0.5),
        "synthetic_calls": sum(1 for row in rows if row["synthetic"]),
    }


def _point_model(rows: list[dict]) -> dict:
    ok = [row for row in rows if row["status"] == "ok"]
    return {
        "calls": len(rows),
        "cost_usd": sum(float(row["cost_usd"] or 0) for row in rows),
        "tokens": sum(int(row["prompt_tokens"] or 0) + int(row["completion_tokens"] or 0) for row in rows),
        "latency_p50_ms": _percentile([float(row["latency_ms"]) for row in ok], 0.5),
    }


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    return quantile(sorted(values), q)


def _ordered(models) -> list[str]:
    names = list(models)
    preferred = [model for model in MODEL_ORDER if model in names]
    rest = sorted(model for model in names if model not in preferred)
    return preferred + rest


def parse_day(value: str) -> datetime:
    return datetime.fromisoformat(value)
