"""Deterministic synthetic demo ledger.

Call rows are simulated traffic for a fictional support bot. Eval rows are the
real runner grading checked-in answers. The 3B candidate is absent from the
call ledger on purpose: the gate fails, so it was not rolled out.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from llmwatch.demo_corpus import SHORT_SCENARIOS, SUMMARIZE, SYSTEM_PROMPT, summarize_thread
from llmwatch.eval.runner import compare_runs, run_suite
from llmwatch.eval.suite import assert_fixture_covers, bundled_fixtures, bundled_suite, load_fixtures, load_suite
from llmwatch.notice import DEMO_FROZEN_AT, DEMO_SEED
from llmwatch.pricing import PriceTable, load_price_table
from llmwatch.providers import fixture_completion_fn
from llmwatch.record import assemble_call
from llmwatch.store import Store

CALL_COUNT = 180
FROZEN = datetime(2026, 11, 8, tzinfo=timezone.utc)
WEIGHTS = {
    "llama-3.1-8b-instant": 0.68,
    "llama-3.3-70b-versatile": 0.32,
}
LATENCY = {
    "llama-3.1-8b-instant": (180.0, 560.0),
    "llama-3.3-70b-versatile": (700.0, 1700.0),
}
HOUR_WEIGHTS = [1, 1, 1, 1, 1, 1, 2, 3, 5, 8, 9, 9, 8, 8, 8, 9, 9, 8, 6, 4, 3, 2, 1, 1]
ERRORS = [
    {
        "error_type": "rate_limit",
        "http_status": 429,
        "attempts": 4,
        "latency_ms": 820.0,
        "message": "Rate limit reached for this model. Gave up after 4 attempts. Last Retry-After was 2s.",
    },
    {
        "error_type": "timeout",
        "http_status": None,
        "attempts": 1,
        "latency_ms": 30000.0,
        "message": "Timed out waiting for the provider.",
    },
    {
        "error_type": "server_error",
        "http_status": 500,
        "attempts": 1,
        "latency_ms": 410.0,
        "message": "Provider returned 500.",
    },
    {
        "error_type": "context_length",
        "http_status": 400,
        "attempts": 1,
        "latency_ms": 140.0,
        "message": "Request exceeded the model context window.",
    },
]


def seed_demo(db_path: str | Path, *, force: bool = False) -> dict:
    path = Path(db_path)
    store = Store(path)
    store.migrate()
    if not force and store.count_calls() > 0:
        counts = store.counts()
        return {"seeded": False, **counts}
    if force:
        store.clear()
    price_table = load_price_table()
    calls = _build_calls(price_table)
    for row in calls:
        store.insert_call(row)
    comparisons = _build_evals(store, price_table)
    return {
        "seeded": True,
        "calls": len(calls),
        "comparisons": [item["id"] for item in comparisons],
        "frozen_at": DEMO_FROZEN_AT,
    }


def _build_calls(price_table: PriceTable) -> list[dict]:
    rng = random.Random(DEMO_SEED)
    drafted: list[tuple[datetime, dict]] = []
    for index in range(CALL_COUNT):
        created = _pick_time(rng)
        model = _pick_model(rng)
        route, user, answer = _pick_exchange(rng, index, model)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]
        prompt_tokens = max(16, len(SYSTEM_PROMPT + user) // 4)
        completion_tokens = max(1, len(answer) // 4)
        latency = _latency(rng, model)
        error = _maybe_error(rng, route)
        call_id = f"call_{index + 1:04d}"
        if error is None:
            response = {
                "id": f"chatcmpl_demo_{call_id}",
                "object": "chat.completion",
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": answer},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                },
            }
            row = assemble_call(
                price_table=price_table,
                model=model,
                messages=messages,
                status="ok",
                latency_ms=latency,
                provider="groq",
                attempts=1,
                response=response,
                http_status=200,
                metadata=_meta(route),
                synthetic=True,
                created_at=_iso(created),
                call_id=call_id,
                token_override=(prompt_tokens, completion_tokens, prompt_tokens + completion_tokens, "simulated"),
            )
        else:
            response = {
                "error": {
                    "message": error["message"],
                    "type": error["error_type"],
                    "code": error["http_status"],
                }
            }
            row = assemble_call(
                price_table=price_table,
                model=model,
                messages=messages,
                status="error",
                latency_ms=error["latency_ms"],
                provider="groq",
                attempts=error["attempts"],
                response=response,
                response_body_text="",
                http_status=error["http_status"],
                error_type=error["error_type"],
                error_message=error["message"],
                metadata=_meta(route),
                synthetic=True,
                created_at=_iso(created),
                call_id=call_id,
            )
            row["token_source"] = "simulated"
        drafted.append((created, row))
    drafted.sort(key=lambda item: (item[0], item[1]["id"]))
    # Ids follow time order so the table and the charts tell the same story.
    ordered = []
    for index, (_created, row) in enumerate(drafted, start=1):
        row["id"] = f"call_{index:04d}"
        if isinstance(row.get("response"), dict) and "id" in row["response"]:
            row["response"]["id"] = f"chatcmpl_demo_{row['id']}"
        ordered.append(row)
    return ordered


def _build_evals(store: Store, price_table: PriceTable) -> list[dict]:
    suite_path = bundled_suite("customer_support")
    suite, fingerprint = load_suite(suite_path)
    fixtures = load_fixtures(bundled_fixtures("customer_support"))
    models = [
        "llama-3.1-8b-instant",
        "llama-3.3-70b-versatile",
        "llama-3.2-3b-preview",
    ]
    assert_fixture_covers(suite, fixtures, models)
    complete = fixture_completion_fn(fixtures, simulate=True, seed=DEMO_SEED)
    created = "2026-11-07T18:00:00Z"
    baseline = run_suite(
        suite,
        model="llama-3.1-8b-instant",
        complete_fn=complete,
        store=store,
        run_id="run_baseline_8b",
        created_at=created,
        label="baseline",
        synthetic=True,
        fingerprint=fingerprint,
        provenance="scripted-fixture",
        price_table=price_table,
    )
    candidate = run_suite(
        suite,
        model="llama-3.3-70b-versatile",
        complete_fn=complete,
        store=store,
        run_id="run_candidate_70b",
        created_at=created,
        label="candidate",
        synthetic=True,
        fingerprint=fingerprint,
        provenance="scripted-fixture",
        price_table=price_table,
    )
    cost_cut = run_suite(
        suite,
        model="llama-3.2-3b-preview",
        complete_fn=complete,
        store=store,
        run_id="run_costcut_3b",
        created_at="2026-11-07T18:05:00Z",
        label="cost-cut",
        synthetic=True,
        fingerprint=fingerprint,
        provenance="scripted-fixture",
        price_table=price_table,
    )
    shared = dict(
        store=store,
        n_boot=2000,
        alpha=0.05,
        seed=DEMO_SEED,
        gate_fail_on_pass_flip=suite.gate.fail_on_pass_flip,
        gate_fail_on_significant_regression=suite.gate.fail_on_significant_regression,
        delta_threshold=suite.gate.delta_threshold,
        synthetic=True,
    )
    first = compare_runs(
        baseline,
        candidate,
        comparison_id="cmp_70b_candidate",
        created_at="2026-11-07T18:00:00Z",
        name="Partial rollout: 70B vs 8B baseline",
        narrative="70B also appears in the simulated call ledger as a partial rollout.",
        **shared,
    )
    second = compare_runs(
        baseline,
        cost_cut,
        comparison_id="cmp_3b_costcut",
        created_at="2026-11-07T18:05:00Z",
        name="Rejected cost-cut: 3B vs 8B baseline",
        narrative="This candidate is not in the call ledger. The gate failed, so it was not rolled out.",
        **shared,
    )
    return [first, second]


def _pick_model(rng: random.Random) -> str:
    draw = rng.random()
    if draw < WEIGHTS["llama-3.1-8b-instant"]:
        return "llama-3.1-8b-instant"
    return "llama-3.3-70b-versatile"


def _pick_exchange(rng: random.Random, index: int, model: str) -> tuple[str, str, str]:
    if rng.random() < 0.18:
        user = summarize_thread(index)
        return "summarize", f"{user}\n\nCase id: NL-DEMO-{index + 1:04d}.", SUMMARIZE["answers"][model]
    scenario = rng.choice(SHORT_SCENARIOS)
    user = f"{scenario['user']}\n\nCase id: NL-DEMO-{index + 1:04d}."
    return scenario["route"], user, scenario["answers"][model]


def _pick_time(rng: random.Random) -> datetime:
    day = rng.choices(range(14), weights=[item + 2 for item in range(14)], k=1)[0]
    hour = rng.choices(range(24), weights=HOUR_WEIGHTS, k=1)[0]
    return FROZEN - timedelta(days=14) + timedelta(
        days=day,
        hours=hour,
        minutes=rng.randrange(60),
        seconds=rng.randrange(60),
    )


def _latency(rng: random.Random, model: str) -> float:
    low, high = LATENCY[model]
    value = math.exp(rng.uniform(math.log(low), math.log(high)))
    if rng.random() < 0.04:
        value *= rng.uniform(2.2, 3.4)
    return round(min(value, 8000.0), 2)


def _maybe_error(rng: random.Random, route: str) -> dict | None:
    chance = 0.12 if route == "summarize" else 0.06
    if rng.random() > chance:
        return None
    if route == "summarize" and rng.random() < 0.55:
        return ERRORS[3]
    return ERRORS[rng.randrange(3)]


def _meta(route: str) -> dict:
    return {
        "route": route,
        "dataset": "synthetic-demo",
        "app": "northline-support-bot",
        "company": "Northline Audio (fictional)",
    }


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
