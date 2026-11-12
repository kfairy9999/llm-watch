# llm-watch

Live demo: [https://llm-watch.kfairley9999.workers.dev](https://llm-watch.kfairley9999.workers.dev) (synthetic data, static build)

A local flight recorder for OpenAI-compatible calls, plus a regression gate for model swaps.

Point a client or a tiny proxy at llm-watch and every chat completion lands in a ledger with the model, prompt, response, token counts, latency, and a cost from a price table you control. The ledger is a SQLite file unless you set a MongoDB URI. A YAML suite then scores model A against model B. If the paired bootstrap interval says quality dropped, or a test flips from pass to fail, the CLI exits 1 so CI can block the swap.

The dashboard in this repo is running on **synthetic demo data**. Northline Audio is fictional. The call traffic, timestamps, token counts, and latencies are simulated. Dollar figures are the bundled price table applied to those tokens. Eval scores are the real runner grading checked-in answers, which is why the UI works with no API key. Nothing on that screen is a live provider trace or a benchmark claim.

![License: MIT](https://img.shields.io/badge/license-MIT-yellow)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB)
![pytest + vitest](https://img.shields.io/badge/tests-pytest%20%2B%20vitest-2ea44f)

## Dashboard

Captured from the seeded demo. The banner on every page says the numbers are synthetic.

![Call ledger with latency chart and a failed gate](docs/screenshots/overview.jpg)

![Calls table](docs/screenshots/calls.jpg)

![One recorded call, labeled synthetic demo](docs/screenshots/call-detail.jpg)

![3B cost-cut fails the gate](docs/screenshots/regression.jpg)

![70B candidate passes as an improvement](docs/screenshots/improvement.jpg)

![Tour of the demo ledger](docs/screenshots/tour.gif)

On this slice the 8B baseline scores 0.667. The 70B candidate scores 1.000 (95% CI on the paired delta about [+0.08, +0.58], zero pass flips). The 3B cost-cut scores 0.187 (CI about [−0.75, −0.23], six pass-to-fail flips) and is absent from the call ledger because the gate failed. Those scores are the runner on scripted answers. The spend on the overview, about a cent, is the illustrative price table on 180 simulated calls, not an invoice.

## Architecture

```mermaid
flowchart LR
  app[Your service]
  sdk[llm-watch SDK]
  proxy[HTTP proxy]
  provider[OpenAI-compatible API]
  db[(SQLite or MongoDB)]
  runner[Eval runner]
  api[FastAPI]
  ui[React dashboard]

  app -->|watch wrapper| sdk
  app -->|OPENAI_BASE_URL| proxy
  sdk --> provider
  proxy --> provider
  sdk --> db
  proxy --> db
  runner -->|fixture or Groq| sdk
  runner --> db
  api --> db
  ui --> api
```

SQLite is the default file. MongoDB is used only when `LLMWATCH_MONGODB_URI` is set on the process that writes the ledger. The static dashboard does not open either database.

The gate is deliberately small:

```mermaid
flowchart TD
  suite[YAML suite] --> a[Score model A]
  suite --> b[Score model B]
  a --> deltas[Paired per-test deltas]
  b --> deltas
  deltas --> boot[Percentile bootstrap of the mean delta]
  deltas --> flips[Pass-to-fail flips]
  boot --> gate{CI entirely below the threshold, or any flip?}
  flips --> gate
  gate -->|yes| fail[Exit 1]
  gate -->|no| ok[Exit 0]
```

## Quickstart

Python 3.11+ and Node 22.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
llmwatch seed
llmwatch serve --host 127.0.0.1 --port 8491
```

In another shell:

```bash
cd dashboard
npm install
npm run dev
```

Open [http://127.0.0.1:8492](http://127.0.0.1:8492). The API docs are at [http://127.0.0.1:8491/docs](http://127.0.0.1:8491/docs).

Fail the demo gate offline:

```bash
llmwatch eval run \
  --model-a llama-3.1-8b-instant \
  --model-b llama-3.2-3b-preview
echo "exit $?"
```

The same command with `--model-b llama-3.3-70b-versatile` exits 0. Add `--json` for a machine-readable comparison.

One-command local run:

```bash
docker compose up --build
```

The dashboard is published on port 8492 and the API on 8491. The ledger lives in the `watchdata` volume and is seeded on an empty database.

## Record a call

`WatchClient` speaks the chat-completions shape, sends a User-Agent on every attempt, and retries 429 and 503. A `Retry-After` value (delta-seconds or an HTTP date) is honored up to a cap. If the header is missing, the wait is full-jitter exponential backoff. One ledger row is written per logical call, with the attempt count. The API key is not stored.

```python
from llmwatch import WatchClient

with WatchClient(
    base_url="https://api.groq.com/openai/v1",
    api_key=os.environ["GROQ_API_KEY"],
    db_path="data/llmwatch.db",
    user_agent="llm-watch/0.1.0",
    provider="groq",
    max_retries=4,
) as client:
    data = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": "Reply with the single word: pong"}],
    )
```

If you already have an OpenAI SDK client, `watch(client, db_path=...)` patches `chat.completions.create` and returns the original response object.

The proxy is the other drop-in. `--upstream` is the provider base URL including `/v1`. Clients keep using `/v1/chat/completions`; the proxy strips the extra `/v1` when it forwards.

```bash
llmwatch proxy \
  --upstream https://api.groq.com/openai/v1 \
  --user-agent llm-watch/0.1.0 \
  --port 8787
# OPENAI_BASE_URL=http://127.0.0.1:8787/v1
```

Streaming responses are buffered so the ledger gets one row, then the original SSE body is returned. The SDK itself rejects `stream=True` and tells you to use the proxy.

Provider `usage` is stored as `token_source=provider`. If usage is missing, tokens are `len(text) // 4` and labeled `estimate`. Demo rows are `simulated`. Cost is always `(prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000`. Unknown models use the table's default rates and `price_source=default`.

`examples/groq_watch.py` builds the Groq client from `GROQ_API_KEY`. Tests never call Groq. They inject a mock transport into `build_client()` and check the User-Agent plus a 429 that honors `Retry-After: 0`.

## MongoDB

SQLite stays the default. The CLI, the local API, and the eval gate use `LLMWATCH_DB` (default `data/llmwatch.db`) and do not need MongoDB installed.

Set `LLMWATCH_MONGODB_URI` when you want each call stored as a document. A free Atlas M0 cluster is enough. This repo does not create an account, turn on billing, or ship a cluster. Put the URI in the environment of the API, the proxy, or the CLI. Do not put it in the dashboard, a frontend env var, or git.

```bash
pip install "llm-watch[mongodb]"
export LLMWATCH_MONGODB_URI='mongodb+srv://USER:PASSWORD@cluster.example.mongodb.net'
export LLMWATCH_MONGODB_DB=llmwatch
llmwatch serve
```

`LLMWATCH_MONGODB_DB` is optional and defaults to `llmwatch`. That variable is the database name, not a path inside the URI. When the URI is set, `--db` and `db_path` are still accepted and are not opened. When the URI is unset, the SQLite file is used, same as before.

`Store(path)` still opens that file even if the URI is set. The CLI, `llmwatch serve`, the proxy, `WatchClient`, and `watch()` call `open_store()`, which is what reads the URI.

Collections, one document per row. `_id` is the existing string id (`call_…`, `run_…`, `res_…`, `cmp_…` from `new_id`, or the id you pass). It is not an ObjectId.

- `calls` — provider, model, endpoint, prompt (messages), response, response_text, prompt_tokens, completion_tokens, total_tokens, token_source, latency_ms, cost_usd, price_source, status, error_type, error_message, http_status, attempts, synthetic, streaming, metadata, created_at
- `eval_runs` — suite_name, suite_fingerprint, model, label, synthetic, provenance, mean_score, pass_rate, n_tests, summary, created_at
- `eval_results` — run_id, test_id, description, prompt, output, score, passed, scorers, latency_ms, cost_usd, prompt_tokens, completion_tokens, metrics_simulated, error
- `eval_comparisons` — suite_name, run_a_id, run_b_id, synthetic, significant_regression, summary, created_at

A result's `run_id` is an `eval_runs` `_id`. A comparison points at two runs. Both backends reject a comparison that names a missing run. SQLite also foreign-keys `eval_results.run_id`. MongoDB writes the run before its results and stamps that run id on each result.

Prompt, response, and metadata are nested fields. They are not JSON text stuffed into a string column.

The eval CI gate stays offline. GitHub Actions runs pytest on SQLite and on an in-memory Mongo stand-in. It does not need Atlas or a secret.

The published dashboard is a static Worker. It reads exported JSON, not MongoDB, and it has no database secret. Point a self-hosted dashboard at the API if those screens should show the MongoDB ledger. The browser only talks to the API. The URI stays on the server.

## Eval gate

Suites live in `llmwatch/suites/`. The demo suite is an instruction-following gate: the fact is in the prompt, and the scorer checks that the model kept the fact and the format. It is not a knowledge benchmark.

Scorers, each returning a score in `[0, 1]` and a pass bit:

| Scorer | Passes when |
| --- | --- |
| `exact` | stripped text equals `expected` |
| `regex` | the pattern matches, or is absent when `forbid: true` |
| `numeric` | the first number is within `tolerance` |
| `json_schema` | fenced or raw JSON validates |
| `llm_judge` | `mode: mock` uses keyword coverage plus a length floor; `mode: live` asks a judge model for `{"score", "reason"}` |

The mock judge writes `offline heuristic, not a model` into the detail string. A test passes only when every scorer passes. The test score is the mean of the scorer scores.

Comparison is paired. For each test id, `delta = score_B - score_A`. A percentile bootstrap (default 2,000 resamples, seedable) produces a 95% interval on the mean delta. The gate fails when that interval lies entirely below `-delta_threshold` (default 0), or when any test goes from pass to fail. One flipped test fails CI even if the mean interval is inconclusive. The report says this is a gate, not a research claim: it does not correct for multiple comparisons, and it assumes the same items were scored on both sides.

## Price table

`llmwatch/prices.default.json` holds illustrative USD per 1M tokens. Override it with `LLMWATCH_PRICES=/path/to.json` or `llmwatch price MODEL --prompt-tokens N --completion-tokens N`. The note in the file, and on the dashboard, says these rates are not an invoice.

## Tests

```bash
pytest
cd dashboard && npm test && npm run build
```

pytest covers the price formula, Retry-After parsing, the SDK ledger (including "the API key is not in the sqlite file"), the OpenAI-style wrapper, proxy forwarding and SSE assembly, every scorer, bootstrap properties, the demo suite's two verdicts, CLI exit codes, and the API disclaimer. A search for `%` does not become a wildcard. The dev extra installs mongomock, and the MongoDB tests run in-process. They do not open a socket and they do not need a URI. vitest covers formatters, the gate copy, and the synthetic banner.

GitHub Actions (`.github/workflows/ci.yml`) runs the Python tests, the dashboard tests, and a static demo build.

## Deploy

The line under the title is a public demo recruiters can open on a phone. It is a static build of this dashboard. `export-demo` writes the seeded ledger (simulated calls plus the eval comparisons the real runner produces) to JSON, and `VITE_DEMO_STATIC=1` makes the UI read those files instead of calling the API. There is no backend, no API key, and no database. The synthetic-demo banner stays on every page.

```bash
pip install -e .
cd dashboard
npm ci
npm run build:demo
```

`npm run build:demo` runs `python3 -m llmwatch.cli export-demo public/demo`, then `vite build` with `VITE_DEMO_STATIC=1`. From the repo root, `make demo-static` does the same thing. Export on its own:

```bash
python -m llmwatch.cli export-demo dashboard/public/demo/
```

`dashboard/wrangler.jsonc` is a static-assets Worker named `llm-watch`. `assets.not_found_handling` is `single-page-application`, so a hard refresh on `/calls/...` or `/evals/...` still loads the app. After the demo build, the site is `dashboard/dist`. Deploy it yourself from `dashboard/` with `npx wrangler deploy`. Cloudflare Pages treats a site with no top-level `404.html` as a single-page app and serves the root document for unknown paths, so the same directory works there too. This repo does not deploy it. The public demo is live at https://llm-watch.kfairley9999.workers.dev.

`render.yaml` remains a blueprint for two Docker services: the API image (`Dockerfile`) and the dashboard image (`dashboard/Dockerfile`). The dashboard container writes `/config.json` from `API_BASE` at startup, so that static build can point at the API without a rebuild. Same-origin `/api` is the default, which is what nginx does in Compose. SQLite on a free container disk disappears on restart unless you attach a volume. Treat the database file as sensitive. It holds prompts and responses, and this project does not add auth. The Compose file and the API image stay on SQLite. To use MongoDB there, install the `mongodb` extra in your own image and set `LLMWATCH_MONGODB_URI` on the API only.

## How it was built

I designed and directed this project and built it with AI coding agents: I set the requirements (record every call with real token costs, gate model swaps on a real eval instead of vibes, and label all demo data as synthetic), reviewed the results, and drove the fixes.

## What I learned

Pair the deltas before you bootstrap. The same item is hard for both models, so the unit of analysis is `score_B - score_A`, not two independent means. A pass-to-fail flip is a better CI signal than a tiny mean drop, and the interval stops one noisy item from failing the build by itself. It is still not a multiple-comparisons correction.

A mock judge is a fixture. Shipping it without a label would launder a keyword heuristic as a model grade, so the scorer detail and the dashboard provenance line both say the answers were scripted.

`Retry-After` is either a number of seconds or an HTTP date. Ignoring it and retrying immediately is how you turn one 429 into a burst. A missing header should back off. A huge header should be capped, or one bad value stalls the process. The cap has to sit above the provider's normal cooldown or you retry too early.

`len(text) // 4` is not a tokenizer. If those counts are unlabeled, the cost chart becomes fiction. The ledger stores `token_source` so an estimate cannot be mistaken for provider usage.

Synthetic demo data needs a column, not only a caption. The API decides the banner from the counts: all synthetic, mixed, or recorded. A recorded call inserted next to the demo flips the banner to mixed. That is the behavior I want if someone later points the SDK at the same file.

Casual traffic and a format-sensitive suite are different surfaces. The 3B answers in a loose support chat can look fine while the suite, which demands exact text and valid JSON, fails. The call log does not include that model because the gate rejected the rollout. I would not quote either view as "the model is good."

## Roadmap

- Incremental streaming, instead of buffering the SSE body
- A live judge with the rubric and the score cached on the run
- Suite versioning past a fingerprint of the YAML
- Per-project ledgers and an auth boundary before this leaves a laptop
- OpenTelemetry export of the same row the ledger writes
- Scorers for tool-call structure and embedding similarity

## License

MIT. Copyright 2026 Kevin Fairley. See [LICENSE](LICENSE).
