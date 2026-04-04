# Project Documentation: Quota Data Server

## Overview

The Quota Data Server (`tmux-status-server`) centralizes claude.ai quota scraping into a standalone Python REST API. Previously, every tmux-status installation ran its own polling daemon with its own session key. Now a single server scrapes claude.ai and serves quota data over HTTP to any number of tmux-status renderers.

The server is always present in the architecture. Single-machine installs run it on localhost. Multi-machine setups run it on a shared host (LAN or Tailscale). The renderer always fetches quota via HTTP -- there is no "standalone mode" vs "client mode" split.

**What changed:**
- New `server/` package: self-contained Python REST API
- `scripts/tmux-claude-status` modified to fetch quota via HTTP with disk cache fallback
- `install.sh` and `uninstall.sh` updated for platform-specific daemon management
- Old `tmux-status-quota-fetch` and `tmux-status-quota-poll` scripts deprecated

## Getting Started

### Prerequisites

| Component | Requirement |
|-----------|-------------|
| Python | 3.10+ |
| pip | Required for server install |
| tmux | 3.2+ |
| curl_cffi | Installed automatically with the server package (Chrome TLS impersonation) |
| Session key | `~/.config/tmux-status/claude-usage-key.json` with your claude.ai `sessionKey` |

Clients (renderers) need no new dependencies -- stdlib `urllib.request` handles HTTP fetches.

### Single-Machine Install

The standard installer handles everything:

```bash
git clone https://github.com/mikeydotio/tmux-status.git ~/projects/tmux-status
~/projects/tmux-status/install.sh
```

This installs the server package via pip, sets up a systemd (Linux) or launchd (macOS) daemon bound to `127.0.0.1:7850`, configures `QUOTA_SOURCE=http://127.0.0.1:7850` in `settings.conf`, and kills any old `tmux-status-quota-poll` processes.

Verify it is running:

```bash
curl -s http://127.0.0.1:7850/health | python3 -m json.tool
```

### Multi-Machine Setup

Run the server on a host that has the session key. Point clients at it.

**On the server host:**

```bash
# Install the server package
pip install ./server/

# Run with network-accessible bind and API key auth
tmux-status-server --host 0.0.0.0 --api-key-file ~/.config/tmux-status/server.key
```

**On each client machine**, edit `~/.config/tmux-status/settings.conf`:

```bash
QUOTA_SOURCE=http://your-server-host:7850
QUOTA_API_KEY=your-api-key-here
QUOTA_CACHE_TTL=30
```

Then reload tmux: `tmux source-file ~/.config/tmux/tmux.conf`

### Session Key

The server reads `~/.config/tmux-status/claude-usage-key.json`. Format:

```json
{"sessionKey": "sk-ant-..."}
```

The file must be `chmod 600` (no group/other read). The server refuses to start if permissions are too open.

## Architecture

### Single-Machine

```
                    SINGLE-MACHINE INSTALL

┌──────────────┐       ┌──────────────────────────────────┐
│  claude.ai   │<------│  tmux-status-server              │
│  (upstream)  │------>│  (systemd/launchd, 127.0.0.1)    │
└──────────────┘       │  scrapes -> in-memory cache       │
                       │  GET /quota, GET /health :7850    │
                       └────────────┬─────────────────────┘
                                    │ localhost HTTP
                                    v
                       ┌──────────────────────────────────┐
                       │  tmux-claude-status (renderer)   │
                       │  fetch -> disk cache -> render    │
                       │  QUOTA_SOURCE=http://127.0.0.1:7850
                       │  QUOTA_CACHE_TTL=0               │
                       └──────────────────────────────────┘
```

### Multi-Machine

```
                    MULTI-MACHINE SETUP

┌──────────────┐       ┌──────────────────────────────────┐
│  claude.ai   │<------│  tmux-status-server (Host A)     │
│  (upstream)  │------>│  --host 0.0.0.0 --api-key-file   │
└──────────────┘       │  scrapes -> in-memory cache       │
                       └────────────┬─────────────────────┘
                                    │ LAN / Tailscale HTTP
                      ┌─────────────┼─────────────┐
                      v             v             v
                 ┌─────────┐  ┌─────────┐  ┌─────────┐
                 │Client B │  │Client C │  │Client D │
                 │TTL=30s  │  │TTL=30s  │  │TTL=30s  │
                 └─────────┘  └─────────┘  └─────────┘
```

### Data Flow: Render Cycle (every 5 seconds)

1. tmux fires `#(tmux-claude-status <pane_pid>)`
2. Script parses Claude session transcript for model/effort
3. Reads `settings.conf` for `QUOTA_SOURCE`, `QUOTA_API_KEY`, `QUOTA_CACHE_TTL`
4. If `QUOTA_CACHE_TTL > 0`: checks cache file mtime. Skips fetch if fresh.
5. HTTP GET `{QUOTA_SOURCE}/quota` (3s timeout, `X-API-Key` header if configured)
6. On success: atomic-write response to `~/.cache/tmux-status/claude-quota.json`
7. On failure: read stale cache (if exists). Hide quota section if stale > 30 min.
8. Output formatted tmux string

### Data Flow: Server Scrape Cycle

1. Background thread wakes after `--interval` seconds (default 300)
2. Re-reads session key from `--key-file` (supports key rotation without restart)
3. Discovers org UUID from claude.ai (cached after first discovery)
4. Fetches usage data via `curl_cffi` with Chrome TLS fingerprint
5. Stores bridge-format dict in memory (GIL-safe reference swap, no lock needed)
6. On failure: sets error status with `"X"` utilization values

### Component Summary

| Component | Location | Purpose |
|-----------|----------|---------|
| `tmux_status_server/server.py` | `QuotaServer` class | HTTP server (Bottle), routes, auth hook, poll thread, signal handling |
| `tmux_status_server/scraper.py` | `fetch_quota()`, `read_session_key()` | Scraping logic, session key validation, error bridge format |
| `tmux_status_server/config.py` | `parse_args()`, `warn_if_exposed()` | CLI argument parsing with secure defaults |
| `tmux_status_server/__main__.py` | Entry point | `python -m tmux_status_server` or `tmux-status-server` CLI |
| `scripts/tmux-claude-status` | `_maybe_fetch_quota()` | Client-side HTTP fetch with cache TTL and atomic disk write |

## API Reference

### `GET /quota`

Returns quota data. Requires `X-API-Key` header when auth is configured.

**Success (200):**

```json
{
  "status": "ok",
  "org_uuid": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "five_hour": {
    "utilization": 42,
    "resets_at": "2026-04-03T18:30:00Z"
  },
  "seven_day": {
    "utilization": 15,
    "resets_at": "2026-04-07T12:00:00Z"
  },
  "timestamp": 1743696000
}
```

**Error condition (200 -- error is in the data, not the HTTP status):**

```json
{
  "status": "expired",
  "five_hour": {"utilization": "X", "resets_at": null},
  "seven_day": {"utilization": "X", "resets_at": null},
  "timestamp": 1743696000,
  "error": "session_key_expired"
}
```

**No data yet (503):**

```json
{
  "status": "starting",
  "five_hour": {"utilization": "X", "resets_at": null},
  "seven_day": {"utilization": "X", "resets_at": null},
  "timestamp": 1743696000,
  "error": "no_data_yet"
}
```

**Auth failure (401):**

```json
{"error": "invalid_or_missing_api_key"}
```

### `GET /health`

Monitoring endpoint. Always 200. Not gated by API key auth.

```json
{
  "status": "ok",
  "uptime_seconds": 3600,
  "version": "0.1.0"
}
```

| `status` Value | Meaning |
|----------------|---------|
| `ok` | Last scrape succeeded |
| `degraded` | Has cached data but last scrape failed |
| `error` | No data at all |

### Error Signaling

When the server encounters problems, it returns `"X"` string values for utilization instead of integers. The renderer displays these as `X%` in the status bar.

| Server Condition | `status` Field | `utilization` Value |
|-----------------|----------------|---------------------|
| Normal | `ok` | Integer 0-100 |
| Session key expired | `expired` | `"X"` |
| Blocked by Cloudflare | `blocked` | `"X"` |
| Rate limited | `rate_limited` | `"X"` |
| No session key file | `no_key` | `"X"` |
| Upstream fetch error | `upstream_error` | `"X"` |
| No data yet (startup) | `starting` | `"X"` |

Users who see `X%` in their status bar should run `curl http://127.0.0.1:7850/health` to diagnose.

## Configuration

### Server CLI Flags

```
tmux-status-server [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--host` | `127.0.0.1` | Address to bind. Use `0.0.0.0` for network access. |
| `--port` | `7850` | Port to bind. |
| `--key-file` | `~/.config/tmux-status/claude-usage-key.json` | Path to claude.ai session key JSON. |
| `--api-key-file` | None (no auth) | Path to API key file for client auth. File should be `chmod 600`. |
| `--interval` | `300` (5 min) | Scrape interval in seconds. |
| `--log-level` | `INFO` | One of: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |

### Client Settings (`settings.conf`)

Located at `~/.config/tmux-status/settings.conf`.

| Key | Default | Description |
|-----|---------|-------------|
| `QUOTA_SOURCE` | `http://127.0.0.1:7850` | URL of the quota server. Leave empty to disable quota fetching. |
| `QUOTA_API_KEY` | (empty) | API key for `X-API-Key` header. Must match server's `--api-key-file` contents. |
| `QUOTA_CACHE_TTL` | `0` | Seconds before re-fetching. `0` = always fetch (good for localhost). `30` = recommended for remote servers. |

### Deprecated Settings

| Key | Replacement |
|-----|-------------|
| `QUOTA_REFRESH_PERIOD` | Server's `--interval` flag |
| `QUOTA_DATA_PATH` | Hardcoded to `~/.cache/tmux-status/claude-quota.json` (still honored if set) |

## Deployment

### systemd (Linux)

The installer copies the unit file automatically. For manual setup:

```bash
mkdir -p ~/.config/systemd/user
cp server/deploy/tmux-status-server.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now tmux-status-server
```

Common commands:

```bash
systemctl --user status tmux-status-server   # check status
systemctl --user restart tmux-status-server  # restart (e.g., after API key rotation)
journalctl --user -u tmux-status-server -f   # follow logs
kill -USR1 $(systemctl --user show -p MainPID tmux-status-server --value)  # force immediate scrape
```

To pass extra flags, override `ExecStart`:

```bash
systemctl --user edit tmux-status-server
```

```ini
[Service]
ExecStart=
ExecStart=%h/.local/bin/tmux-status-server --host 0.0.0.0 --api-key-file %h/.config/tmux-status/server.key --interval 120
```

### launchd (macOS)

The installer copies the plist automatically. For manual setup:

```bash
cp server/deploy/io.mikey.tmux-status-server.plist ~/Library/LaunchAgents/
# Edit the plist to expand ~ to your actual home directory in ProgramArguments
launchctl load ~/Library/LaunchAgents/io.mikey.tmux-status-server.plist
```

Common commands:

```bash
launchctl list | grep tmux-status-server   # check if running
launchctl unload ~/Library/LaunchAgents/io.mikey.tmux-status-server.plist  # stop
launchctl load ~/Library/LaunchAgents/io.mikey.tmux-status-server.plist    # start
```

### Docker

Build and run from the `server/` directory:

```bash
cd server/
docker build -t tmux-status-server .

docker run -d \
  --name tmux-status-server \
  -p 7850:7850 \
  -v /path/to/claude-usage-key.json:/app/key.json:ro \
  tmux-status-server \
  --key-file /app/key.json
```

With API key authentication:

```bash
docker run -d \
  --name tmux-status-server \
  -p 7850:7850 \
  -v /path/to/claude-usage-key.json:/app/key.json:ro \
  -v /path/to/server.key:/app/api.key:ro \
  tmux-status-server \
  --key-file /app/key.json --api-key-file /app/api.key
```

The Dockerfile uses `python:3.12-slim`, exposes port 7850, and defaults to `--host 0.0.0.0`.

### Signal Handling

| Signal | Behavior |
|--------|----------|
| `SIGTERM` | Graceful shutdown: stops poll thread, stops HTTP server, exits 0 |
| `SIGINT` | Same as SIGTERM |
| `SIGUSR1` | Wake poll thread for immediate out-of-cycle scrape |

### Uninstall

```bash
~/projects/tmux-status/uninstall.sh
```

This stops and removes the daemon (systemd or launchd), uninstalls the pip package, removes symlinks, and optionally cleans up cache and config directories.

## Development

### Project Structure

```
server/
  pyproject.toml                        # Package metadata, entry point, deps
  Dockerfile                            # Container deployment
  deploy/
    tmux-status-server.service          # systemd user unit
    io.mikey.tmux-status-server.plist   # launchd plist
  tmux_status_server/
    __init__.py                         # Version string
    __main__.py                         # Entry point
    config.py                           # CLI args, security warnings
    scraper.py                          # Session key reading, quota fetching
    server.py                           # QuotaServer class, Bottle app, routes
  tests/
    test_config.py                      # CLI parsing, warn_if_exposed
    test_scraper.py                     # Session key, fetch_quota, error bridge
    test_server.py                      # Routes, auth, WSGI integration, poll
    test_validate_gaps.py               # Client fetch, cache TTL
    test_deploy.py                      # systemd/launchd/Dockerfile structure
    test_package.py                     # pyproject.toml, package metadata
```

### Running Tests

```bash
cd server/
python3 -m pytest tests/ -v
```

309 tests, ~6.5 seconds. No external services required -- all HTTP calls are mocked.

### Dependencies

**Server (runtime):** `bottle>=0.12.25` (CVE-2022-31799 fix), `curl_cffi>=0.5` (Chrome TLS)

**Server (test):** `pytest`, `webtest` (WSGI integration testing)

**Client (renderer):** None new. Uses stdlib `urllib.request`.

### Key Design Patterns

- **Atomic writes:** Client disk cache and all bridge files use `tmp + os.replace()`. No partial reads possible.
- **Silent failure:** The renderer catches all exceptions and falls back to stale cache. No error output to tmux.
- **GIL-safe reference swap:** Server shares data between the HTTP thread and poll thread via `self._cached_data = new_data`. No lock needed.
- **Error sanitization:** API responses use machine-readable error codes only. Raw exception text appears in server logs, never in responses or cache files.

## Architecture Decision Records

### ADR-001: Server Always Present (No Dual-Mode Architecture)

**Status:** Accepted

**Context:** The original design considered two modes: standalone (local poller writes to cache file) and client (fetches from remote server). This creates two code paths, potential race conditions between the poller and renderer on the cache file, and branching logic in the renderer.

**Decision:** The server is always present. Single-machine installs run it on localhost. The renderer always fetches via HTTP. There is one architecture, one code path.

**Consequences:** Simpler renderer code (always HTTP fetch). Eliminates race conditions on the cache file. Requires a running server process even for single-machine installs. Daemon management (systemd/launchd) becomes a mandatory part of installation.

### ADR-002: Server Is the Canonical Scraper

**Status:** Accepted

**Context:** The scraping logic existed in `scripts/tmux-status-quota-fetch`. Moving it to the server creates a question: should both locations have copies, should there be a shared library, or should the server be the single source?

**Decision:** `server/tmux_status_server/scraper.py` owns all scraping logic. The old scripts (`tmux-status-quota-fetch`, `tmux-status-quota-poll`) are deprecated.

**Consequences:** Single source of truth for scraping. When claude.ai changes their API, only one file needs updating. Old scripts remain in the repo but are not used by default installations. No shared library to package or version.

### ADR-003: Default Bind to 127.0.0.1

**Status:** Accepted

**Context:** The server holds a credential (session key). Binding to `0.0.0.0` by default would expose the API to the local network on any machine.

**Decision:** Default bind is `127.0.0.1`. Users opt in to network exposure with `--host 0.0.0.0`. When binding to non-localhost without `--api-key-file`, the server logs a warning.

**Consequences:** Safe default for single-machine installs. Multi-machine setups require explicit configuration. No accidental credential exposure on dual-homed machines.

### ADR-004: Error Signaling with "X" Utilization Values

**Status:** Accepted

**Context:** When scraping fails, the renderer needs to communicate the error condition to the user via the tmux status bar without breaking the format string.

**Decision:** Error states use `"X"` string values for utilization instead of integers. The renderer displays `X%`. Users check `/health` for details.

**Consequences:** Clear visual signal that something is wrong. Does not break tmux format strings. Requires the renderer to handle both integer and string types for utilization fields. Numeric sentinels (e.g., `-1`) were rejected because `-1%` is confusing.

### ADR-005: Bottle as HTTP Framework

**Status:** Accepted

**Context:** The server handles trivial traffic (<10 clients, <1 req/s). Framework choice should minimize dependencies.

**Decision:** Bottle -- zero additional dependencies (single-file library), built-in server, Flask-like API.

**Consequences:** No need for gunicorn or uvicorn. Built-in server is sufficient for the traffic profile. Bottle's `before_request` hook semantics require `abort()` to stop request processing (returning a value does not short-circuit). This was a source of a security bug during development (fixed in TS-26).

### ADR-006: Disk Cache as Fallback

**Status:** Accepted

**Context:** When the server is unreachable (restart, crash, network issue), the renderer needs something to display.

**Decision:** The renderer always writes successful responses to disk cache (`~/.cache/tmux-status/claude-quota.json`). On fetch failure, it reads stale cache. Stale data older than 30 minutes causes the quota section to be hidden.

**Consequences:** Graceful degradation during server restarts. No flicker in the status bar during brief outages. Disk I/O on every successful fetch (mitigated by atomic write and SSD). `QUOTA_CACHE_TTL=0` for localhost means every 5s render cycle writes to disk, but the data is small (<500 bytes).

### ADR-007: API Key Via File (Not CLI Flag or Env Var)

**Status:** Accepted

**Context:** The server needs optional API key authentication for multi-machine deployments. The key must be provided securely.

**Decision:** Preferred method is `--api-key-file` pointing to a `chmod 600` file. CLI flags are visible in `ps`. Environment variables are visible in `/proc/PID/environ`.

**Consequences:** Most secure default. Requires creating and permissioning a file. The client-side key is stored in `settings.conf` as `QUOTA_API_KEY` (plaintext) -- this is a known trade-off documented as escalated issue TS-11.

## Known Issues

Five issues were identified during the forge pipeline and deferred as future work.

### TS-11: Plaintext API Key in `settings.conf`

The client-side `QUOTA_API_KEY` is stored in plaintext in `~/.config/tmux-status/settings.conf`. While `settings.conf` should be user-readable only, this is less secure than a dedicated key file with restricted permissions. A future improvement could support a `QUOTA_API_KEY_FILE` directive or read from a keyring.

### TS-12: Unused Imports in `__main__.py`

`__main__.py` imports `parse_args` and `warn_if_exposed` from `config` but never uses them (it delegates to `_server_main()` which performs its own imports). No functional impact; cosmetic cleanup.

### TS-13: Module-Level Global State in Scraper

`scraper.py` caches the org UUID in a module-level global (`_org_uuid`). This works correctly under the single-server model but would complicate future multi-account support or unit test isolation. The global is reset on 401/403 errors.

### TS-22: SIGTERM Does Not Shut Down HTTP Server

The `SIGTERM` handler sets a shutdown flag and stops the poll thread, but Bottle's built-in server does not expose a clean shutdown mechanism. The process relies on the daemon manager (systemd/launchd) to force-kill after timeout. In practice this works but is not a clean shutdown.

### TS-23: Client Fetch Embedded in Shell Script (Untestable)

The `_maybe_fetch_quota()` function is an inline Python block inside the bash script `scripts/tmux-claude-status`. It cannot be directly unit-tested. The server-side contract is fully tested, and the function's existence is verified structurally. A future refactor could extract the renderer's Python logic into a testable module.

## Test Coverage

309 tests passing, 0 failures, ~6.5 seconds runtime.

### Requirement Coverage Matrix

| Requirement | Tested | Test File | Notes |
|-------------|--------|-----------|-------|
| Server scrapes claude.ai, serves via REST | Yes | `test_server.py` | Mock scraper + endpoint tests |
| `GET /quota` returns bridge JSON | Yes | `test_server.py` | Success, error, 503 states |
| `GET /health` for monitoring | Yes | `test_server.py` | ok/degraded/error states, version, uptime |
| Optional API key auth (hmac) | Yes | `test_server.py` | Mock + WSGI integration |
| Client fetches from `QUOTA_SOURCE` URL | Yes | `test_validate_gaps.py` | Real HTTP via mock server |
| Disk cache with TTL | Yes | `test_validate_gaps.py` | Fresh/stale/missing/zero-TTL |
| Error signaling with "X" values | Yes | `test_scraper.py`, `test_server.py` | Error bridge + None/X distinction |
| Server installable independently | Yes | `test_deploy.py`, `test_config.py` | Dockerfile, systemd, launchd, pyproject |
| Standalone mode unchanged | Yes | `test_validate_gaps.py` | Empty `source_url` no-ops |
| Platform-specific daemons | Yes | `test_deploy.py` | Unit file + plist structure verified |
| Auth bypass fix (TS-26) | Yes | `test_server.py` | WSGI proves `abort()` stops pipeline |
| Empty key file bypass (TS-27) | Yes | `test_server.py` | `_load_api_key` returns None |
| Renderer None guard (TS-28) | Partial | `test_server.py` | Server contract tested; renderer is shell |
| WSGI auth data leakage (TS-29) | Yes | `test_server.py` | 6 WSGI + 5 exhaustive tests |

### Test Files

| File | Test Count | Focus |
|------|-----------|-------|
| `test_server.py` | ~180 | Routes, auth hooks, WSGI integration, poll thread, error handling |
| `test_scraper.py` | ~50 | Session key validation, quota fetching, error bridge, HTTP mocking |
| `test_config.py` | ~30 | CLI parsing, defaults, warn_if_exposed |
| `test_validate_gaps.py` | ~30 | Client-side fetch, cache TTL, silent failure |
| `test_deploy.py` | ~15 | systemd unit, launchd plist, Dockerfile correctness |
| `test_package.py` | ~4 | pyproject.toml, version, entry point |
