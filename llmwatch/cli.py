"""Command line for the ledger, the proxy, the regression gate, and the static demo."""

from __future__ import annotations

import argparse
import json
import os
import sys

from llmwatch.demo_export import export_demo
from llmwatch.eval.report import render_report
from llmwatch.eval.runner import compare_runs, run_suite
from llmwatch.eval.suite import (
    assert_fixture_covers,
    bundled_fixtures,
    bundled_suite,
    load_fixtures,
    load_suite,
)
from llmwatch.notice import __version__
from llmwatch.pricing import load_price_table
from llmwatch.providers import fixture_completion_fn, groq_completion_fn
from llmwatch.seed import seed_demo
from llmwatch.store import Store
from llmwatch.text import new_id


def entry() -> None:
    raise SystemExit(main())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="llmwatch",
        description="Log OpenAI-compatible calls and fail CI when a model swap regresses.",
    )
    parser.add_argument("--version", action="version", version=f"llm-watch {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    seed = sub.add_parser("seed", help="write the synthetic demo ledger")
    seed.add_argument("--db", default=_default_db())
    seed.add_argument("--force", action="store_true", help="replace an existing ledger")
    seed.set_defaults(func=_cmd_seed)

    export = sub.add_parser("export-demo", help="write static dashboard JSON for the synthetic demo")
    export.add_argument("out", help="directory for the JSON files, for example dashboard/public/demo")
    export.add_argument("--db", default=None, help="ledger to export; default seeds a temporary demo")
    export.set_defaults(func=_cmd_export_demo)

    serve = sub.add_parser("serve", help="start the read API")
    serve.add_argument("--db", default=_default_db())
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8491)
    serve.add_argument("--no-seed", action="store_true")
    serve.set_defaults(func=_cmd_serve)

    proxy = sub.add_parser("proxy", help="forward an OpenAI-compatible base URL and log calls")
    proxy.add_argument("--upstream", required=True, help="base URL including /v1")
    proxy.add_argument("--db", default=_default_db())
    proxy.add_argument("--host", default="127.0.0.1")
    proxy.add_argument("--port", type=int, default=8787)
    proxy.add_argument("--user-agent", default="llm-watch/0.1.0")
    proxy.add_argument("--api-key", default=os.environ.get("UPSTREAM_API_KEY") or os.environ.get("GROQ_API_KEY"))
    proxy.add_argument("--max-retries", type=int, default=2)
    proxy.set_defaults(func=_cmd_proxy)

    suite_path = sub.add_parser("suite-path", help="print a bundled suite path")
    suite_path.add_argument("name", nargs="?", default="customer_support")
    suite_path.set_defaults(func=_cmd_suite_path)

    price = sub.add_parser("price", help="price a token count with the configured table")
    price.add_argument("model")
    price.add_argument("--prompt-tokens", type=int, required=True)
    price.add_argument("--completion-tokens", type=int, required=True)
    price.set_defaults(func=_cmd_price)

    eval_cmd = sub.add_parser("eval", help="run or compare eval suites")
    eval_sub = eval_cmd.add_subparsers(dest="eval_cmd", required=True)
    run = eval_sub.add_parser("run", help="score model A and model B, then apply the gate")
    run.add_argument("--suite", default=str(bundled_suite("customer_support")))
    run.add_argument("--model-a", required=True)
    run.add_argument("--model-b", required=True)
    run.add_argument("--provider", choices=("fixture", "groq"), default="fixture")
    run.add_argument("--fixture", default=None, help="YAML of scripted outputs; default is the bundled demo")
    run.add_argument("--db", default=_default_db())
    run.add_argument("--name", default=None)
    run.add_argument("--json", action="store_true")
    run.add_argument("--no-simulate-metrics", action="store_true")
    run.add_argument("--n-boot", type=int, default=2000)
    run.add_argument("--seed", type=int, default=20261108)
    run.set_defaults(func=_cmd_eval_run)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


def _cmd_seed(args: argparse.Namespace) -> int:
    result = seed_demo(args.db, force=args.force)
    print(json.dumps(result, indent=2))
    return 0


def _cmd_export_demo(args: argparse.Namespace) -> int:
    result = export_demo(args.out, db_path=args.db)
    print(json.dumps(result, indent=2))
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    os.environ["LLMWATCH_DB"] = str(args.db)
    os.environ["LLMWATCH_SEED"] = "0" if args.no_seed else "1"
    uvicorn.run("llmwatch.api.main:create_app", host=args.host, port=args.port, factory=True)
    return 0


def _cmd_proxy(args: argparse.Namespace) -> int:
    import uvicorn

    from llmwatch.proxy import create_proxy_app

    app = create_proxy_app(
        upstream=args.upstream,
        db_path=args.db,
        user_agent=args.user_agent,
        api_key=args.api_key,
        max_retries=args.max_retries,
        provider="groq" if "groq" in args.upstream else "openai-compatible",
    )
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def _cmd_suite_path(args: argparse.Namespace) -> int:
    print(bundled_suite(args.name))
    return 0


def _cmd_price(args: argparse.Namespace) -> int:
    table = load_price_table()
    cost, source = table.compute_cost(args.model, args.prompt_tokens, args.completion_tokens)
    print(json.dumps({"model": args.model, "cost_usd": cost, "price_source": source, "note": table.note}))
    return 0


def _cmd_eval_run(args: argparse.Namespace) -> int:
    suite, fingerprint = load_suite(args.suite)
    table = load_price_table()
    store = Store(args.db)
    store.migrate()
    if args.provider == "fixture":
        fixture_path = args.fixture or str(bundled_fixtures("customer_support"))
        fixtures = load_fixtures(fixture_path)
        assert_fixture_covers(suite, fixtures, [args.model_a, args.model_b])
        complete = fixture_completion_fn(
            fixtures,
            simulate=not args.no_simulate_metrics,
            seed=args.seed,
        )
        provenance = "scripted-fixture"
        synthetic = False
    else:
        complete = groq_completion_fn(db_path=args.db, price_table=table)
        provenance = "live"
        synthetic = False
    stamp = _now()
    run_a = run_suite(
        suite,
        model=args.model_a,
        complete_fn=complete,
        store=store,
        run_id=new_id("run"),
        created_at=stamp,
        label="A",
        synthetic=synthetic,
        fingerprint=fingerprint,
        provenance=provenance,
        price_table=table,
    )
    run_b = run_suite(
        suite,
        model=args.model_b,
        complete_fn=complete,
        store=store,
        run_id=new_id("run"),
        created_at=stamp,
        label="B",
        synthetic=synthetic,
        fingerprint=fingerprint,
        provenance=provenance,
        price_table=table,
    )
    comparison = compare_runs(
        run_a,
        run_b,
        store=store,
        comparison_id=new_id("cmp"),
        created_at=stamp,
        name=args.name or f"{args.model_b} vs {args.model_a}",
        gate_fail_on_pass_flip=suite.gate.fail_on_pass_flip,
        gate_fail_on_significant_regression=suite.gate.fail_on_significant_regression,
        delta_threshold=suite.gate.delta_threshold,
        n_boot=args.n_boot,
        seed=args.seed,
        synthetic=synthetic,
    )
    if args.json:
        print(json.dumps(comparison, indent=2))
    else:
        print(render_report(comparison))
    return 1 if comparison["failed_gate"] else 0


def _default_db() -> str:
    return os.environ.get("LLMWATCH_DB", "data/llmwatch.db")


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


if __name__ == "__main__":
    entry()
