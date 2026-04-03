# Work Handoff

## Session Summary
- **Session**: session-execute-007
- **Duration**: ~7 minutes
- **Stories completed**: 1
- **Stories attempted**: 1
- **Status**: Session limit reached (1/1 stories per session)

## What Happened
Seventh execution session. Implemented TS-8 (client-side HTTP fetch in renderer — urllib.request-based quota fetch with cache TTL, atomic writes, X error handling) — passed evaluation on first attempt. Wave 2 is now complete (TS-7 + TS-8). Wave 3 (TS-9, TS-10) is now unblocked.

## Stories Completed This Session
- TS-8: Client-side HTTP fetch in renderer — modified `scripts/tmux-claude-status` to add `_maybe_fetch_quota()` function using urllib.request, reads QUOTA_SOURCE/QUOTA_API_KEY/QUOTA_CACHE_TTL from settings.conf, atomic cache writes via temp+os.replace, handles "X" utilization values in Python output and bash bar_char/display functions. Silent failure on fetch exceptions.

## Cumulative Progress
- TS-2: Done (session 1) — config module
- TS-3: Done (session 2) — scraper module
- TS-4: Done (session 3) — settings and gitignore
- TS-5: Done (session 4) — server packaging and entry points
- TS-6: Done (session 5) — deployment files (systemd, launchd, Dockerfile)
- TS-7: Done (session 6) — server HTTP module (QuotaServer, endpoints, auth, polling)
- TS-8: Done (session 7) — client-side HTTP fetch in renderer
- TS-9: Todo (NOW UNBLOCKED) — install script modifications
- TS-10: Todo (NOW UNBLOCKED) — uninstall script modifications

## Current Blockers
None. TS-9 and TS-10 are both unblocked (wave 3, final wave).

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
- Renderer Python block parses settings.conf in a single loop for ALL settings (QUOTA_DATA_PATH, QUOTA_SOURCE, QUOTA_API_KEY, QUOTA_CACHE_TTL)
- `_maybe_fetch_quota()` defined as function in embedded Python, called inline
- Fetch timeout is 3 seconds (hardcoded, not configurable — renderer runs every 5s)
- `json.loads(data)` used to validate JSON before atomic write to cache
- `os.makedirs(cache_dir, exist_ok=True)` ensures cache directory exists before write
- Non-numeric bar_char input returns red ✕ character
- `fmt_quota_pct()` bash helper: "X" stays "X", numeric gets "%"

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
- `quota_cache_ttl` Python default is 30 (fallback when no settings.conf); installed settings.conf has 0
- Only literal "error" status triggers "X" output; other error statuses (expired, blocked) keep pct=0 defaults — bash color override already handles visual signaling for those
- shlex.quote() used for quota pct output to safely handle "X" string values in eval

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
- `scripts/tmux-claude-status` — Renderer with HTTP fetch, settings parsing, "X" handling (TS-8)
- `config/settings.example.conf` — User-facing settings with server keys (TS-4)
- `.gitignore` — Security exclusions and Python artifacts (TS-4)
- `server/tests/test_config.py` — 22 tests for config module
- `server/tests/test_scraper.py` — 36 tests for scraper module
- `server/tests/test_package.py` — 21 tests for package structure
- `server/tests/test_server.py` — 75 tests for server module
- `server/tests/test_deploy.py` — 34 tests for deployment files

### Test State
- 188 tests pass (pytest): `source ~/.venv/bin/activate && python3 -m pytest server/tests/ -v`
- pytest installed in `/home/mikey/.venv` (created via `uv venv`)
- No flaky tests
- No tests exist for `scripts/tmux-claude-status` (shell script, no test framework)

## What's Next
- TS-9 (install script modifications) and TS-10 (uninstall script modifications) are both unblocked — wave 3, final wave
- Both modify shell scripts (install.sh, uninstall.sh) for server daemon management
- 2 stories remaining total
