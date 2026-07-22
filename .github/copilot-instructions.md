# Copilot Instructions for mcp-tavily

`mcp-tavily` is an MCP (Model Context Protocol) proxy server that aggregates multiple Tavily API
keys behind a single MCP interface, giving clients higher effective quota and automatic failover
while staying 100% tool-compatible with the official `@tavily/mcp` server.

## Environment & commands

- **Python runtime:** always use `/media/data/venv/bin/python` (a pre-built venv), not system Python.
- **Install deps:** `/media/data/venv/bin/pip install -r requirements.txt`
- **Run the server locally:** `/media/data/venv/bin/python app/main.py` (reads config from `.env` in repo root)
- **Run all tests:** `/media/data/venv/bin/python -m unittest discover -s tests -v`
- **Run a single test file:** `/media/data/venv/bin/python -m unittest tests.test_manager -v`
- **Run a single test case:** `/media/data/venv/bin/python -m unittest tests.test_integration.TestMCPIntegration.test_round_robin_and_retry_on_429 -v`
- **Type check:** `/media/data/venv/bin/python -m mypy app --ignore-missing-imports`
- **Docker:** `docker-compose up -d --build` (port 18000→8000)
- **MCP transport:** Streamable HTTP only (no stdio/SSE). Endpoint is
  `http://<MCP_HOST>:<PORT><MCP_PATH>` (defaults `0.0.0.0:8000/mcp`); configurable via `MCP_HOST`,
  `PORT`, `MCP_PATH` env vars, see `TavilyAggregator.start()` in `app/main.py`.

## Architecture (read `app/main.py` + `app/core/*` together to understand the flow)

Request flow: `MCP Client → TavilyAggregator (FastMCP) → KeyPoolManager.execute_with_retry → TavilyClient(api_key)`

- **`app/main.py` — `TavilyAggregator(FastMCP)`**: registers the 4 official Tavily tools
  (`tavily-search`, `tavily-extract`, `tavily-crawl`, `tavily-map`). Each tool method builds a
  closure `_call(api_key)` that constructs a fresh `TavilyClient(api_key=...)` per call and hands
  it to `key_manager.execute_with_retry`. Tool signatures/descriptions must stay aligned with the
  official Tavily MCP so clients don't need config changes (descriptions live in
  `app/constants/tools.py`).
- **`app/core/config.py` — `ConfigManager`**: parses `TAVILY_API_KEYS` (comma-separated) from
  `.env`, without depending on `python-dotenv` (manual line parsing) to stay lightweight. A
  background thread (`start_watching`, 5s poll) watches `.env` mtime and calls `reload()`, which
  diffs old vs new raw keys and, on change, invokes all registered callbacks — this is how hot
  reload without restart is implemented. `TavilyAggregator.__init__` wires
  `config_manager.register_callback(key_manager.update_keys)`.
- **`app/core/manager.py` — `KeyPoolManager`**: owns the `Key` list and does round-robin dispatch
  under an `asyncio.Lock` (`get_next_key`). `execute_with_retry(func)` loops up to
  `len(keys)` attempts, calling `func(key.raw_key)`; on failure it inspects the exception string
  for `"429"/"rate limit"` (→ `key.set_cooldown(60)`) or `"401"/"unauthorized"/"invalid"`
  (→ `KeyStatus.ERROR`), then retries with the next key. It raises once all keys are exhausted or
  no active key remains.
- **`app/core/key.py` — `Key`**: state machine with `ACTIVE / COOLDOWN / EXHAUSTED / ERROR`.
  `check_status()` lazily flips `COOLDOWN → ACTIVE` once `cooldown_until` has passed. All mutation
  is guarded by a per-key `threading.Lock`. Keys are always logged/displayed via `label`, the
  masked form (`tvly-abcd...wxyz`) from `_mask_key` — never log `raw_key`.
- **`app/tasks/monitor.py` — `monitor_usage_task`**: background asyncio task (started from the
  FastMCP lifespan context in `main.py`) that polls Tavily's `/usage` endpoint every
  `interval_minutes` (default 10) for every current key and calls `key.update_usage(usage, limit)`,
  which can proactively flip a key to `EXHAUSTED` before it ever gets a 429 from a real search call.

## Conventions specific to this repo

- New Tavily tools/parameters must mirror the official `@tavily/mcp` tool schema exactly (name,
  args, defaults) — this project's entire value proposition is drop-in compatibility.
- Any function that ends up calling the Tavily API must go through
  `key_manager.execute_with_retry`, not call `TavilyClient` directly, so failover/cooldown logic
  applies uniformly.
- Never log a full raw API key; use `Key.label` / `_mask_key`.
- This repo follows a documentation-heavy workflow (see `GEMINI.md`): design docs live under
  `docs/design/` (`ARCH_OVERVIEW.md` is the source of truth for architecture — update it when the
  design changes), requirements under `docs/requirements/`, and open questions/tech debt in the
  root `TODO.md`. Keep `docs/design/ARCH_OVERVIEW.md` in sync with real behavior when you change
  `KeyPoolManager`, `ConfigManager`, or the monitor task.
