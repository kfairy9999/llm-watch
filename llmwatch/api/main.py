"""Read API for the dashboard. Writes happen through the SDK, proxy, and CLI."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from llmwatch.api.metrics import summarize, timeseries
from llmwatch.notice import DEMO_DATASET, DEMO_FROZEN_AT, __version__, disclaimer_for
from llmwatch.pricing import load_price_table
from llmwatch.seed import seed_demo
from llmwatch.store import Store


def create_app(db_path: str | Path | None = None, seed: bool | None = None) -> FastAPI:
    path = Path(db_path or os.environ.get("LLMWATCH_DB", "data/llmwatch.db"))
    if seed is None:
        seed = os.environ.get("LLMWATCH_SEED", "1") != "0"
    store = Store(path)
    store.migrate()
    if seed:
        seed_demo(path, force=False)
    app = FastAPI(title="llm-watch", version=__version__)
    origins = [item.strip() for item in os.environ.get("LLMWATCH_CORS", "*").split(",") if item.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.store = store
    app.state.db_path = path
    prices = load_price_table()

    @app.get("/")
    def root() -> dict:
        return {"service": "llm-watch", "version": __version__, "docs": "/docs", "health": "/api/health"}

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "version": __version__}

    @app.get("/api/meta")
    def meta() -> dict:
        counts = store.counts()
        disclaimer = disclaimer_for(**counts)
        return {
            "version": __version__,
            "dataset_label": DEMO_DATASET if counts["synthetic_calls"] or counts["synthetic_comparisons"] else None,
            "frozen_at": DEMO_FROZEN_AT if disclaimer and "Synthetic demo" in disclaimer else None,
            "disclaimer": disclaimer,
            "price_note": prices.note,
            **counts,
        }

    @app.get("/api/prices")
    def price_table() -> dict:
        return prices.public_dict()

    @app.get("/api/models")
    def models() -> dict:
        return {"models": store.distinct_models()}

    @app.get("/api/calls")
    def calls(
        model: str | None = None,
        status: str | None = None,
        q: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = Query(25, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ) -> dict:
        total, rows = store.list_calls(
            model=model,
            status=status,
            q=q,
            since=since,
            until=until,
            limit=limit,
            offset=offset,
        )
        return {"total": total, "limit": limit, "offset": offset, "calls": rows}

    @app.get("/api/calls/{call_id}")
    def call_detail(call_id: str) -> dict:
        row = store.get_call(call_id)
        if row is None:
            raise HTTPException(status_code=404, detail="call not found")
        return row

    @app.get("/api/metrics/summary")
    def metrics_summary() -> dict:
        return summarize(store.call_metrics())

    @app.get("/api/metrics/timeseries")
    def metrics_timeseries() -> dict:
        return timeseries(store.call_metrics())

    @app.get("/api/evals/comparisons")
    def comparisons() -> dict:
        return {"comparisons": store.list_comparisons()}

    @app.get("/api/evals/comparisons/{comparison_id}")
    def comparison_detail(comparison_id: str) -> dict:
        row = store.get_comparison(comparison_id)
        if row is None:
            raise HTTPException(status_code=404, detail="comparison not found")
        return row

    return app
