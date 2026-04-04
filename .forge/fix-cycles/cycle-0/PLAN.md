# Implementation Plan

## Requirements

| ID | Requirement | Type | Priority |
|----|-------------|------|----------|
| R1 | Server package with `config.py` (CLI arg parsing, defaults, validation) | functional | high |
| R2 | Server package with `scraper.py` (scrape claude.ai for quota data, reused from `tmux-status-quota-fetch`) | functional | high |
| R3 | Server package with `server.py` (Bottle HTTP server, `/quota` and `/health` endpoints, auth middleware, background poll thread) | functional | high |
| R4 | Server package entry points (`__init__.py`, `__main__.py`, `pyproject.toml` with console_scripts) | functional | high |
| R5 | `GET /quota` returns bridge-format JSON (status, five_hour, seven_day, timestamp) with error signaling (`"X"` utilization) | functional | high |
| R6 | `GET /health` returns status JSON (status, uptime_seconds, version), exempt from auth | functional | high |
| R7 | API key auth via `X-API-Key` header, `hmac.compare_digest()`, loaded from `--api-key-file` | functional | medium |
| R8 | Key file permission enforcement: refuse to start if session key file or API key file is world-readable | non-functional | medium |
| R9 | Signal handling: SIGTERM/SIGINT for shutdown, SIGUSR1 for immediate scrape | functional | medium |
| R10 | Modify `tmux-claude-status` to fetch quota from HTTP server (urllib), write to disk cache, respect `QUOTA_CACHE_TTL` | functional | high |
| R11 | Backward compat: `QUOTA_DATA_PATH` still honored if set; `QUOTA_REFRESH_PERIOD` ignored gracefully | functional | medium |
| R12 | Update `settings.example.conf`: add `QUOTA_SOURCE`, `QUOTA_API_KEY`, `QUOTA_CACHE_TTL`; deprecate old keys | functional | high |
| R13 | Modify `install.sh`: `pip install ./server/`, platform detection, daemon setup (systemd/launchd), update messaging | functional | high |
| R14 | Modify `uninstall.sh`: daemon teardown, server uninstall | functional | high |
| R15 | Create `.gitignore` with security exclusions (`claude-usage-key.json`, `*.key`, `*.pem`, `.env`, `__pycache__/`, `*.pyc`) | non-functional | high |
| R16 | Systemd user unit file for Linux daemon management | functional | medium |
| R17 | Launchd plist file for macOS daemon management | functional | medium |
| R18 | Dockerfile for containerized deployment | functional | low |
| R19 | Default bind `127.0.0.1:7850`; warning when binding non-localhost without auth | non-functional | medium |
| R20 | Error sanitization: generic error codes in API responses, no raw exceptions | non-functional | medium |
| R21 | Server logging: Python logging to stdout, INFO default, configurable via `--log-level` | non-functional | low |
| R22 | Thread safety: reference swap for cached data under GIL, no lock needed | non-functional | medium |
| R23 | Startup 503 response with `"starting"` status when no data yet | functional | medium |
| R24 | Bottle version pinned `>=0.12.25` (CVE-2022-31799 fix) | non-functional | high |

## Task Waves

### Wave 1 (parallel -- no dependencies)

#### T1.1: Server config module
- **Requirement(s)**: R1, R19, R21
- **Description**: Create `server/tmux_status_server/config.py` with argparse-based CLI configuration. Parse `--host` (default `127.0.0.1`), `--port` (default `7850`), `--key-file` (session key path, default `~/.config/tmux-status/claude-usage-key.json`), `--api-key-file` (optional), `--interval` (default `300`), `--log-level` (default `INFO`). Return a namespace/dataclass with validated config. Include the non-localhost-without-auth warning logic as a function.
- **Acceptance criteria**:
  - [ ] File exists at `server/tmux_status_server/config.py`
  - [ ] Contains a function (or class) that parses CLI args using `argparse`
  - [ ] Default values: host=`127.0.0.1`, port=`7850`, interval=`300`, log_level=`INFO`
  - [ ] `--key-file` defaults to `~/.config/tmux-status/claude-usage-key.json` (with `~` expansion)
  - [ ] `--api-key-file` is optional (default `None`)
  - [ ] Contains a function that logs a WARNING when host is not `127.0.0.1` and `api_key_file` is `None`
  - [ ] No external dependencies (stdlib only)
- **Expected files**: `server/tmux_status_server/config.py`
- **Estimated scope**: small

#### T1.2: Server scraper module
- **Requirement(s)**: R2, R5, R8, R20, R22
- **Description**: Create `server/tmux_status_server/scraper.py` by extracting and refactoring the scraping logic from `scripts/tmux-status-quota-fetch`. The module provides: `read_session_key(key_file_path)` (reads JSON key file, checks 600 perms, checks expiry), `fetch_quota(session_key)` (org discovery with caching, usage fetch via curl_cffi, returns bridge-format dict), and error result generation (returns dicts with `"X"` utilization on error). The scraper must never raise exceptions to callers -- all errors are returned as bridge-format dicts with appropriate status codes.
- **Acceptance criteria**:
  - [ ] File exists at `server/tmux_status_server/scraper.py`
  - [ ] Contains `read_session_key(path)` function that reads a JSON file and returns a dict with `sessionKey` and optional `expiresAt`, or an error dict
  - [ ] `read_session_key` checks file permissions via `os.stat()` and returns an error dict if mode allows group or other read (i.e., `stat.st_mode & 0o077 != 0`)
  - [ ] Contains `fetch_quota(session_key)` function that returns a bridge-format dict with keys: `status`, `five_hour`, `seven_day`, `timestamp`
  - [ ] On error, returned dict has `"utilization": "X"` and `"resets_at": null` for both windows, and an `error` key with a generic string code
  - [ ] Uses `curl_cffi` for HTTP requests with `impersonate="chrome131"`
  - [ ] Contains `REQUEST_HEADERS` dict matching the existing scraper's headers
  - [ ] Org UUID is cached as a module-level variable (or within a class) to avoid re-discovery
  - [ ] Imports `curl_cffi` only (no `bottle`, no `urllib`)
  - [ ] No raw exception text appears in any returned dict -- only generic error codes like `session_key_expired`, `blocked`, `upstream_error`, `no_key`, `rate_limited`
- **Expected files**: `server/tmux_status_server/scraper.py`
- **Estimated scope**: medium

#### T1.3: Settings and gitignore updates
- **Requirement(s)**: R12, R15
- **Description**: Update `config/settings.example.conf` to add the new `QUOTA_SOURCE`, `QUOTA_API_KEY`, and `QUOTA_CACHE_TTL` settings with comments, and mark `QUOTA_DATA_PATH` and `QUOTA_REFRESH_PERIOD` as deprecated (commented out with deprecation notes). Create a root `.gitignore` with security exclusions and Python bytecode patterns.
- **Acceptance criteria**:
  - [ ] `config/settings.example.conf` contains `QUOTA_SOURCE=http://127.0.0.1:7850` (uncommented, as a default)
  - [ ] `config/settings.example.conf` contains `# QUOTA_API_KEY=` (commented out, optional)
  - [ ] `config/settings.example.conf` contains `QUOTA_CACHE_TTL=0` (uncommented, default for localhost)
  - [ ] `config/settings.example.conf` contains a deprecation comment near `QUOTA_REFRESH_PERIOD` stating it is replaced by the server's `--interval` flag
  - [ ] `config/settings.example.conf` contains a deprecation comment near `QUOTA_DATA_PATH` stating it is now internal
  - [ ] `.gitignore` exists at repository root
  - [ ] `.gitignore` contains entries for: `claude-usage-key.json`, `*.key`, `*.pem`, `.env`, `__pycache__/`, `*.pyc`, `*.egg-info/`
- **Expected files**: `config/settings.example.conf`, `.gitignore`
- **Estimated scope**: small

#### T1.4: Server packaging and entry points
- **Requirement(s)**: R4, R24
- **Description**: Create the server package scaffolding: `server/tmux_status_server/__init__.py` (with `__version__ = "0.1.0"`), `server/tmux_status_server/__main__.py` (minimal entry point that calls main), and `server/pyproject.toml` (with metadata, dependencies `bottle>=0.12.25` and `curl_cffi>=0.5`, `python_requires>=3.10`, and `console_scripts` entry point `tmux-status-server`).
- **Acceptance criteria**:
  - [ ] `server/tmux_status_server/__init__.py` exists and contains `__version__ = "0.1.0"`
  - [ ] `server/tmux_status_server/__main__.py` exists and is executable as `python -m tmux_status_server`
  - [ ] `server/pyproject.toml` exists with `[project]` section containing `name = "tmux-status-server"`
  - [ ] `pyproject.toml` declares `dependencies` including `bottle>=0.12.25` and `curl_cffi>=0.5`
  - [ ] `pyproject.toml` declares `requires-python = ">=3.10"`
  - [ ] `pyproject.toml` declares `[project.scripts]` with `tmux-status-server` entry point
  - [ ] `__main__.py` imports and calls a `main()` function (the actual main will come from T2.1)
- **Expected files**: `server/tmux_status_server/__init__.py`, `server/tmux_status_server/__main__.py`, `server/pyproject.toml`
- **Estimated scope**: small

#### T1.5: Deployment files (systemd, launchd, Dockerfile)
- **Requirement(s)**: R16, R17, R18
- **Description**: Create the three deployment configuration files. Systemd user unit at `server/deploy/tmux-status-server.service`. Launchd plist at `server/deploy/io.mikey.tmux-status-server.plist`. Dockerfile at `server/Dockerfile` using `python:3.12-slim` base.
- **Acceptance criteria**:
  - [ ] `server/deploy/tmux-status-server.service` exists and is a valid systemd unit file
  - [ ] Service unit has `ExecStart=%h/.local/bin/tmux-status-server`, `Restart=on-failure`, `RestartSec=10`, `WantedBy=default.target`
  - [ ] `server/deploy/io.mikey.tmux-status-server.plist` exists and is a valid XML plist
  - [ ] Plist has `Label` = `io.mikey.tmux-status-server`, `RunAtLoad` = true, `KeepAlive` = true
  - [ ] `server/Dockerfile` exists and uses `FROM python:3.12-slim`
  - [ ] Dockerfile installs the package via `pip install .` and sets `CMD` or `ENTRYPOINT` to `tmux-status-server`
  - [ ] Dockerfile exposes port 7850
- **Expected files**: `server/deploy/tmux-status-server.service`, `server/deploy/io.mikey.tmux-status-server.plist`, `server/Dockerfile`
- **Estimated scope**: small

### Wave 2 (depends on Wave 1)

#### T2.1: Server HTTP module
- **Requirement(s)**: R3, R5, R6, R7, R9, R19, R20, R22, R23
- **Depends on**: T1.1 (config), T1.2 (scraper), T1.4 (packaging)
- **Description**: Create `server/tmux_status_server/server.py` -- the main module that wires everything together. This is the core of the server. It contains: (1) a `QuotaServer` class that holds the Bottle app, config, cached data, and background poll thread; (2) `GET /quota` route that returns the cached bridge data (or 503 starting response if no data, or 401 on bad auth); (3) `GET /health` route that returns status/uptime/version (exempt from auth); (4) `before_request` hook for API key auth using `hmac.compare_digest()`; (5) background thread that calls `scraper.fetch_quota()` at the configured interval, re-reading the session key file on each cycle (not caching at startup) so key rotation takes effect without restart; (6) immediate first scrape on startup before accepting HTTP connections (or within first few seconds) so users don't wait 300s for first data; (7) signal handlers for SIGTERM/SIGINT (shutdown) and SIGUSR1 (immediate scrape); (8) `main()` function that parses config, sets up logging, starts the server. Update `__main__.py` to call `server.main()`.
- **Acceptance criteria**:
  - [ ] File exists at `server/tmux_status_server/server.py`
  - [ ] Contains a class (e.g., `QuotaServer`) that creates a `bottle.Bottle()` app instance
  - [ ] `/quota` route returns JSON with `Content-Type: application/json`
  - [ ] `/quota` returns 503 with `{"status": "starting", ...}` when no data has been fetched yet
  - [ ] `/quota` returns 401 with `{"error": "invalid_or_missing_api_key"}` when auth is configured and header is missing/wrong
  - [ ] `/quota` returns 200 with bridge-format JSON on success (keys: `status`, `five_hour`, `seven_day`, `timestamp`)
  - [ ] `/health` route returns 200 with JSON containing `status`, `uptime_seconds`, `version`
  - [ ] `/health` is NOT gated by API key auth
  - [ ] Auth check uses `hmac.compare_digest()` (import present and used)
  - [ ] Background thread calls `scraper.fetch_quota()` and stores result via reference swap (no `threading.Lock`)
  - [ ] Background thread re-reads the session key file on every scrape cycle (no startup caching) so key rotation works without restart
  - [ ] First scrape happens immediately on startup (not waiting for the full interval to elapse)
  - [ ] `signal.signal()` calls for `SIGTERM`, `SIGINT`, and `SIGUSR1` are present
  - [ ] `main()` function exists, calls config parsing, sets up logging format `%(asctime)s %(levelname)s %(message)s`, starts the server
  - [ ] When host is not `127.0.0.1` and no API key file is set, a WARNING is logged at startup
  - [ ] `__main__.py` is updated to import and call `server.main()`
  - [ ] Error responses use generic codes only (no raw exception text)
  - [ ] `bottle.run()` call uses `host` and `port` from config
- **Expected files**: `server/tmux_status_server/server.py`, `server/tmux_status_server/__main__.py` (update)
- **Estimated scope**: large

#### T2.2: Client-side HTTP fetch in renderer
- **Requirement(s)**: R10, R11
- **Depends on**: T1.3 (settings format)
- **Description**: Modify `scripts/tmux-claude-status` to add HTTP quota fetching and handle error signaling. In the embedded Python block, before the existing bridge-file read logic: (1) parse `QUOTA_SOURCE`, `QUOTA_API_KEY`, and `QUOTA_CACHE_TTL` from `settings.conf`; (2) if `QUOTA_SOURCE` is set, check cache file mtime against TTL; (3) if stale or TTL=0, fetch from `{QUOTA_SOURCE}/quota` using `urllib.request` with 3s timeout and optional `X-API-Key` header; (4) on success, atomic-write response to cache file; (5) on any failure, silently fall through to existing stale cache read. Also modify the bridge-file read logic to handle error statuses (expired, blocked, etc.) — when status is not "ok", display "X%" instead of "0%" by checking if utilization is a string. Preserve backward compat: if `QUOTA_DATA_PATH` is set, use it as the cache path.
- **Acceptance criteria**:
  - [ ] `scripts/tmux-claude-status` contains `urllib.request` import in the embedded Python block
  - [ ] Settings parsing reads `QUOTA_SOURCE`, `QUOTA_API_KEY`, and `QUOTA_CACHE_TTL` from `settings.conf`
  - [ ] When `QUOTA_SOURCE` is set and `QUOTA_CACHE_TTL` is 0, an HTTP fetch is attempted on every invocation
  - [ ] When `QUOTA_SOURCE` is set and `QUOTA_CACHE_TTL` > 0, the cache file mtime is checked and fetch is skipped if `time.time() - mtime < QUOTA_CACHE_TTL`
  - [ ] HTTP request uses `urllib.request.Request` with `timeout=3`
  - [ ] When `QUOTA_API_KEY` is set, the `X-API-Key` header is added to the request
  - [ ] On successful fetch, response is written to cache file using temp-file + `os.replace()` (atomic write)
  - [ ] On any exception during fetch, execution continues silently (bare `except Exception: pass`)
  - [ ] If `QUOTA_DATA_PATH` is set in settings.conf, it is used as the cache file path (backward compat)
  - [ ] The existing bridge-file read code (lines ~111-152 of current file) still runs after the fetch block
  - [ ] No new external dependencies (stdlib `urllib.request` only)
  - [ ] When quota status is an error (expired, blocked, etc.), `five_hour_pct` and `seven_day_pct` output "X" instead of 0 — the bash `bar_char` and `printf` handle the string "X" to display "X%" in the status bar
  - [ ] The `bar_char` function in bash gracefully handles non-numeric input (the `2>/dev/null` on comparisons already handles this — verify it renders a neutral bar character)
- **Expected files**: `scripts/tmux-claude-status`
- **Estimated scope**: medium

### Wave 3 (depends on Wave 2)

#### T3.1: Install script modifications
- **Requirement(s)**: R13
- **Depends on**: T2.1 (server package complete), T1.5 (deploy files exist)
- **Description**: Modify `install.sh` to: (1) install the server package via `pip install ./server/` (or `pip install --user ./server/`); (2) detect the OS (Linux vs macOS); (3) on Linux, copy the systemd unit to `~/.config/systemd/user/`, run `systemctl --user daemon-reload`, `systemctl --user enable tmux-status-server`, `systemctl --user start tmux-status-server`; (4) on macOS, copy the plist to `~/Library/LaunchAgents/`, run `launchctl load` on it; (5) update the SCRIPTS array to include the new entry point name for cleanup purposes; (6) replace the old quota messaging (curl_cffi check, poller instructions) with server-based messaging; (7) ensure `QUOTA_SOURCE=http://127.0.0.1:7850` is in the default settings.conf; (8) detect and kill any running `tmux-status-quota-poll` processes (migration from old poller); (9) start the daemon before reloading tmux config so the renderer can immediately reach the server.
- **Acceptance criteria**:
  - [ ] `install.sh` contains `pip install` or `pip3 install` command targeting `./server/` or `$INSTALL_DIR/server/`
  - [ ] `install.sh` contains OS detection logic (checking `uname -s` for `Linux` vs `Darwin`)
  - [ ] On Linux path: copies systemd unit to `~/.config/systemd/user/tmux-status-server.service`
  - [ ] On Linux path: runs `systemctl --user daemon-reload` and `systemctl --user enable --now tmux-status-server`
  - [ ] On macOS path: copies plist to `~/Library/LaunchAgents/io.mikey.tmux-status-server.plist`
  - [ ] On macOS path: runs `launchctl load` on the plist
  - [ ] Old quota section (curl_cffi check, poller instructions) is replaced with server-based messaging
  - [ ] Final success output mentions the server and how to check its status
  - [ ] Detects and kills any running `tmux-status-quota-poll` processes with a migration message (e.g., `pkill -f tmux-status-quota-poll` or `pgrep`/`kill`)
  - [ ] Daemon start happens before tmux config reload so the renderer can reach the server immediately
- **Expected files**: `install.sh`
- **Estimated scope**: medium

#### T3.2: Uninstall script modifications
- **Requirement(s)**: R14
- **Depends on**: T2.1 (knows what server artifacts to remove), T1.5 (deploy file names)
- **Description**: Modify `uninstall.sh` to: (1) stop and disable the daemon (systemd on Linux, launchctl on macOS); (2) remove the daemon config files; (3) uninstall the server package via `pip uninstall tmux-status-server`; (4) add `tmux-status-server` to the cleanup logic for symlinks if applicable.
- **Acceptance criteria**:
  - [ ] `uninstall.sh` contains OS detection logic (checking `uname -s` for `Linux` vs `Darwin`)
  - [ ] On Linux path: runs `systemctl --user stop tmux-status-server` and `systemctl --user disable tmux-status-server`
  - [ ] On Linux path: removes `~/.config/systemd/user/tmux-status-server.service`
  - [ ] On macOS path: runs `launchctl unload` on the plist
  - [ ] On macOS path: removes `~/Library/LaunchAgents/io.mikey.tmux-status-server.plist`
  - [ ] Runs `pip uninstall -y tmux-status-server` or `pip3 uninstall -y tmux-status-server`
  - [ ] Daemon teardown happens before symlink removal and config removal
- **Expected files**: `uninstall.sh`
- **Estimated scope**: medium

## Requirement Traceability

| Requirement | Tasks | Coverage |
|-------------|-------|----------|
| R1: Server config module | T1.1 | full |
| R2: Server scraper module | T1.2 | full |
| R3: Server HTTP module | T2.1 | full |
| R4: Server packaging | T1.4 | full |
| R5: GET /quota response format | T1.2, T2.1 | full (T1.2 produces dicts, T2.1 serves them) |
| R6: GET /health endpoint | T2.1 | full |
| R7: API key auth | T2.1 | full |
| R8: Key file permission enforcement | T1.2 | full |
| R9: Signal handling | T2.1 | full |
| R10: Client HTTP fetch | T2.2 | full |
| R11: Backward compat (QUOTA_DATA_PATH, QUOTA_REFRESH_PERIOD) | T2.2, T1.3 | full (T2.2 honors QUOTA_DATA_PATH, T1.3 documents deprecation) |
| R12: Settings update | T1.3 | full |
| R13: Install script | T3.1 | full |
| R14: Uninstall script | T3.2 | full |
| R15: .gitignore | T1.3 | full |
| R16: Systemd unit | T1.5 | full |
| R17: Launchd plist | T1.5 | full |
| R18: Dockerfile | T1.5 | full |
| R19: Default bind + warning | T1.1, T2.1 | full (T1.1 defines defaults, T2.1 logs warning) |
| R20: Error sanitization | T1.2, T2.1 | full (T1.2 in dicts, T2.1 in HTTP responses) |
| R21: Server logging | T1.1, T2.1 | full (T1.1 parses level, T2.1 configures logging) |
| R22: Thread safety | T2.1 | full |
| R23: Startup 503 | T2.1 | full |
| R24: Bottle version pin | T1.4 | full |

## Dependency Graph

```
Wave 1 (all parallel):
  T1.1 config ─────────────┐
  T1.2 scraper ────────────┤
  T1.4 packaging ──────────┼──► T2.1 server HTTP module
  T1.5 deploy files ───────┤         │
  T1.3 settings + gitignore┼──► T2.2 client fetch
                            │         │
                            │    Wave 3:
                            ├──► T3.1 install.sh
                            └──► T3.2 uninstall.sh
```

## Resumption Points

**After Wave 1 complete**: The server package has all its parts (config, scraper, packaging, deploy files) but no HTTP wiring. Settings and gitignore are updated. The project is in a consistent state -- existing functionality is unchanged, new files are added but not yet integrated. Safe to pause here.

**After Wave 2 complete**: The server is fully functional (T2.1) and the renderer can fetch from it (T2.2). A developer could manually `pip install ./server/` and `tmux-status-server` to test. The install/uninstall scripts are not yet updated, so automated deployment is not available. Safe to pause here.

**After Wave 3 complete**: Full feature complete. Install and uninstall handle the server lifecycle. This is the final state.

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| `curl_cffi` import and API differences between versions | Scraper may fail at runtime if curl_cffi API changed | Pin `curl_cffi>=0.5` in pyproject.toml; copy the exact import pattern from the existing working `tmux-status-quota-fetch` |
| Bottle's built-in server thread interaction with signal handlers | Signals may not be delivered to the correct thread | Set signal handlers in the main thread before calling `bottle.run()`; use `threading.Event` for cross-thread communication (pattern already proven in `tmux-status-quota-poll`) |
| Systemd user units require `loginctl enable-linger` on some distros | Daemon may not start at boot for non-root users | Document in install output; add `loginctl enable-linger` call if available |
| macOS plist path expansion (`~` in ProgramArguments) | launchd may not expand `~` in all contexts | Use absolute path with `$HOME` substitution during install |
| Existing installations with `QUOTA_DATA_PATH` set | Could break if we change cache file location | T2.2 explicitly preserves backward compat by checking for `QUOTA_DATA_PATH` in settings |

## Test Strategy

Testing infrastructure is OUT of scope for this implementation (the project has no test suite). However, the QA review identified the following minimum viable testing approach for future consideration:

- **Framework:** `pytest` + `webtest` (WSGI test client for Bottle). Two test deps total.
- **Only mock:** `curl_cffi.requests.get` (external service). Everything else runs real: Bottle via WSGI, file system via temp dirs, auth via real `hmac.compare_digest`.
- **Priority test areas:** API key auth bypass (8 cases), error sanitization (3 cases), key file permission enforcement (6 cases), `/quota` response contract (7 cases), client fetch function (9 cases).
- **What NOT to test:** Actual claude.ai scraping, tmux rendering output, install/uninstall scripts, systemd/launchd lifecycle, performance.
- **Install:** `cd server/ && pip install -e ".[test]" && pytest`

This strategy is documented here for the future test implementation phase. The current plan focuses on functional code only.

## Risk Register

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| `round("X")` in renderer when error status is non-"ok" | **Low** — current code guards with `if quota_status == "ok"` but shows 0% on errors instead of "X%" | High | T2.2 explicitly adds "X" handling for error statuses |
| Existing `tmux-status-quota-poll` still running after upgrade | **High** — dual writers to cache file, stale data | Likely | T3.1 adds `pkill -f tmux-status-quota-poll` migration step |
| Server first-scrape delay (up to 300s of no data on fresh install) | **Medium** — bad first impression, user thinks it's broken | Likely | T2.1 requires immediate first scrape on startup |
| Session key rotated while server running | **Medium** — server keeps using expired key | Likely | T2.1 requires re-reading key file each scrape cycle |
| `curl_cffi` import/API differences between versions | **Medium** — scraper fails at runtime | Possible | Pin `curl_cffi>=0.5`, copy exact import pattern from existing working script |
| Bottle WSGIRef single-threaded with multiple panes hitting TTL=0 | **Low** — requests serialize, 3s client timeout may fire | Possible | Acceptable for <10 clients; document as known limitation |
| macOS 14+ blocks `pip install` outside venvs (externally-managed) | **Medium** — install fails on modern macOS | Possible | install.sh should use `pip install --user` or `--break-system-packages` with warning |
| Systemd user units require `loginctl enable-linger` on some distros | **Low** — daemon doesn't start at boot | Possible | Document in install output |
| Port 7850 already in use | **Low** — server fails to bind | Unlikely | Server logs clear error; install.sh reports failure |

## Scope Boundaries

### IN scope
- Server package (config, scraper, HTTP, packaging)
- Client-side HTTP fetch in renderer
- Settings.conf updates
- Install/uninstall script modifications for server lifecycle
- Deployment files (systemd, launchd, Dockerfile)
- .gitignore creation
- Backward compatibility with `QUOTA_DATA_PATH`

### OUT of scope
- Removing or deleting deprecated scripts (`tmux-status-quota-fetch`, `tmux-status-quota-poll`) -- they remain in place
- Test suite creation -- the project has no tests and adding them is a separate initiative
- TLS/HTTPS support on the server
- Multiple session key support
- PyPI publishing
- Changes to the context hook (`tmux-status-context-hook.js`)
- Changes to `tmux-git-status`, `tmux-status-session`, or `overlay/status.conf`
- Stale data visual indicator (dimmed colors when cache is old)
- README updates

## Deviation Log

| Task | Planned | Actual | Impact | Decision |
|------|---------|--------|--------|----------|
| (empty -- execution has not started) | | | | |
