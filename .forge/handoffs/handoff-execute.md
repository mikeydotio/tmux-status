# Work Handoff

## Session Summary
- **Session**: session-execute-006
- **Duration**: ~16 minutes
- **Stories completed**: 1
- **Stories attempted**: 1
- **Status**: Session limit reached (1/1 stories per session)

## What Happened
Sixth execution session. Implemented TS-7 (server HTTP module — QuotaServer class, Bottle endpoints, API key auth, background poll thread, signal handling) — passed evaluation on first attempt. Wave 2 is partially complete (TS-7 done, TS-8 remaining). Also fixed stale story states: TS-3 (verifying→done) and TS-5 (todo→done) were inconsistent with prior handoff.

## Stories Completed This Session
- TS-7: Server HTTP module — created `server/tmux_status_server/server.py` with QuotaServer class, /quota and /health endpoints, X-API-Key auth via hmac.compare_digest, background poll thread with immediate first scrape and per-cycle session key re-read, SIGTERM/SIGINT/SIGUSR1 signal handling, reference swap for thread safety. Updated `__main__.py` to delegate to server.main(). 75 new tests (188 total).

## Cumulative Progress
- TS-2: Done (session 1) — config module
- TS-3: Done (session 2) — scraper module
- TS-4: Done (session 3) — settings and gitignore
- TS-5: Done (session 4) — server packaging and entry points
- TS-6: Done (session 5) — deployment files (systemd, launchd, Dockerfile)
- TS-7: Done (session 6) — server HTTP module (QuotaServer, endpoints, auth, polling)
- TS-8: Todo (NOW UNBLOCKED) — client-side HTTP fetch in renderer
- TS-9: Todo (blocked by TS-8) — install script modifications
- TS-10: Todo (blocked by TS-8) — uninstall script modifications

## Current Blockers
None. TS-8 is now unblocked (last story in wave 2). After TS-8, wave 3 (TS-9, TS-10) becomes unblocked.

## Working Context

### Patterns Established
- Config module uses module-level constants for defaults (DEFAULT_HOST, DEFAULT_PORT, etc.)
- Scraper module uses module-level `_org_uuid` cache variable
- Tilde expansion via `os.path.expanduser()` applied post-parse, not in defaults
- Warning function is a separate callable (`warn_if_exposed(args)`)
- `_error_bridge(status, error_code)` helper builds standardized error dicts with "X" utilization
- `_http_get(url, session_key)` wraps curl_cffi with lazy import inside function body
- REQUEST_HEADERS dict is verbatim copy from existing `tmux-status-quota-fetch`
- Tests use `sys.path.insert` to import from `server/tmux_status_server/`
- Test files use unittest-style classes under pytest
- AST-based import verification test pattern used in all modules
- `__init__.py` exports `__version__` only — no re-exports of submodules
- Logger uses `logging.getLogger(__name__)` in all modules
- Bottle imported lazily inside `_create_app()` method (mirrors curl_cffi lazy import in scraper)
- `self._bottle_run` captured during `_create_app()` to avoid re-import in `run()`
- Error handlers (404/500) use the `response` object from the enclosing closure scope
- Tests use `_make_mock_bottle()` helper and `_make_server()` factory that patch `sys.modules`
- Auth hook uses `before_request` with early return for /health exemption
- Background thread uses `threading.Event` for shutdown and wake signaling
- Reference swap pattern: `self._cached_data = new_data` (no threading.Lock)

### Micro-Decisions
- `read_session_key(path)` returns `{"error": "insecure_permissions"}` not `"no_key"` for bad permissions
- `fetch_quota` uses `status_map` dict for HTTP→error code mapping: {401: "session_key_expired", 403: "blocked", 429: "rate_limited"}
- `_http_get` lazy-imports `curl_cffi` to allow tests to mock without needing the actual package
- `extract_window()` defined as nested function inside `fetch_quota`
- Deprecated settings get `# DEPRECATED: <reason>` comment prefix
- .gitignore separates "Secrets and credentials" from "Python" sections
- `__main__.py` imports `server.main as _server_main` for clear delegation
- `pyproject.toml` build-backend uses `setuptools.backends._legacy:_Backend`
- Dockerfile uses `--no-cache-dir` with pip install
- Dockerfile COPY order: pyproject.toml first, then package dir (cache-friendly layering)
- QuotaServer stores `_last_scrape_ok` boolean separately from `_cached_data` for health status
- `_do_scrape()` re-reads session key via `read_session_key(self.key_file)` at top of each cycle
- `_poll_loop()` calls `_do_scrape()` before entering the while loop (immediate first scrape)
- `bottle.run()` called with `quiet=True` to suppress Bottle's default stdout logging
- API key loaded once at `run()` start, not per-request (design choice for performance)
- Health endpoint status logic: ok (data + last scrape ok), degraded (data + last scrape failed), error (no data)

### Code Landmarks
- `server/tmux_status_server/config.py` — CLI arg parsing and network exposure warning (TS-2)
- `server/tmux_status_server/scraper.py` — Session key reading and quota fetching (TS-3)
- `server/tmux_status_server/server.py` — QuotaServer class, HTTP endpoints, auth, polling, signals (TS-7)
- `server/tmux_status_server/__init__.py` — Package init with __version__ = "0.1.0" (TS-5)
- `server/tmux_status_server/__main__.py` — Entry point delegating to server.main() (TS-5, updated TS-7)
- `server/pyproject.toml` — Package metadata, deps, console script entry point (TS-5)
- `server/deploy/tmux-status-server.service` — Systemd user unit for Linux (TS-6)
- `server/deploy/io.mikey.tmux-status-server.plist` — launchd plist for macOS (TS-6)
- `server/Dockerfile` — Docker container image (TS-6)
- `server/tests/test_config.py` — 22 tests for config module
- `server/tests/test_scraper.py` — 36 tests for scraper module
- `server/tests/test_package.py` — 21 tests for package structure (updated for TS-7)
- `server/tests/test_server.py` — 75 tests for server module
- `server/tests/test_deploy.py` — 34 tests for deployment files
- `config/settings.example.conf` — User-facing settings with server keys (TS-4)
- `.gitignore` — Security exclusions and Python artifacts (TS-4)

### Test State
- 188 tests pass (pytest): `source ~/.venv/bin/activate && python3 -m pytest server/tests/ -v`
- pytest installed in `/home/mikey/.venv` (created via `uv venv`)
- No flaky tests

## What's Next
- TS-8 (client-side HTTP fetch in renderer — modify `scripts/tmux-claude-status` to fetch quota from server via urllib.request) is the only remaining wave 2 story
- After TS-8: TS-9 (install) and TS-10 (uninstall) become unblocked (wave 3)
- 3 stories remaining total
