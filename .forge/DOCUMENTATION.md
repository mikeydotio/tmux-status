# Project Documentation

## Overview

**tmux-status** is a 3-line tmux status bar for Claude Code developers. It displays Claude session metadata (model name, effort level, context window usage, API quota), filesystem path with git status, and a window tab bar -- all without touching keybindings or preferences.

The **Quota Data Service** (v0.1.0) is a centralized REST API server that replaces the old per-machine quota scraping scripts (`tmux-status-quota-fetch` and `tmux-status-quota-poll`, now deleted). It scrapes claude.ai for 5-hour and 7-day API usage quota and serves the data over HTTP. The renderer (`tmux-claude-status`) fetches quota from this server via `urllib.request`, with a local disk cache as fallback.

### What changed

| Before | After |
|--------|-------|
| Each machine ran `tmux-status-quota-poll` + `tmux-status-quota-fetch` | Single server process (`tmux-status-server`) scrapes and serves via HTTP |
| `curl_cffi` required on every machine | `curl_cffi` required only on the server |
| No authentication | Optional API key authentication (`X-API-Key` header) |
| No health monitoring | `GET /health` endpoint with status, uptime, version |
| Bridge file written directly by scraper | Server caches in memory; renderer writes local disk cache from HTTP response |

## Getting Started

### Prerequisites

- **tmux 3.2+** (multi-line status support)
- **Python 3.10+**
- **bash**, **git**, **node** (Node.js)
- **pip** (for installing the server package)

The server package pulls in two Python dependencies: `bottle` (HTTP framework) and `curl_cffi` (Chrome TLS fingerprint impersonation for bypassing Cloudflare on claude.ai).

### Installation

One-line install (clones repo, symlinks scripts, installs server, sets up daemon):

```bash
curl -fsSL https://raw.githubusercontent.com/mikeydotio/tmux-status/main/install.sh | bash
```

Or clone first:

```bash
git clone https://github.com/mikeydotio/tmux-status.git ~/projects/tmux-status
cd ~/projects/tmux-status
./install.sh
```

The installer performs these steps:
1. Clones/updates the repo to `~/projects/tmux-status` (configurable via `TMUX_STATUS_DIR`)
2. Symlinks 5 scripts to `~/.local/bin/`
3. Creates default config at `~/.config/tmux-status/`
4. Adds a `source-file` line to your tmux.conf
5. Configures the Claude Code `statusLine` hook for context tracking
6. Installs the `tmux-status-server` Python package via pip
7. Kills any legacy `tmux-status-quota-poll` processes
8. Installs and starts a platform daemon (systemd on Linux, launchd on macOS)

### First Run Verification

After installation, verify everything is working:

```bash
# Check the server is running
curl -s http://127.0.0.1:7850/health | python3 -m json.tool
```

Expected output:

```json
{
    "status": "ok",
    "uptime_seconds": 42,
    "version": "0.1.0"
}
```

If the health status is `"error"`, the server has not yet completed its first scrape or the session key is missing. Check the session key setup below.

```bash
# Check quota data
curl -s http://127.0.0.1:7850/quota | python3 -m json.tool
```

Then reload tmux:

```bash
tmux source-file ~/.config/tmux/tmux.conf
```

### Session Key Setup

The server needs a claude.ai session key to scrape quota data. Create the key file:

```bash
cat > ~/.config/tmux-status/claude-usage-key.json << 'EOF'
{"sessionKey": "sk-ant-...", "expiresAt": "2026-05-01T00:00:00Z"}
EOF
chmod 600 ~/.config/tmux-status/claude-usage-key.json
```

Get the `sessionKey` value from your browser cookies on claude.ai. The `expiresAt` field is optional but enables expiry warnings in the status bar (turns red within 24 hours of expiration).

**Important:** The key file must have `0600` or `0400` permissions (owner-only). The server rejects files readable by group or other and returns an `insecure_permissions` error.

### Uninstall

```bash
~/projects/tmux-status/uninstall.sh
```

This stops the daemon, removes the systemd/launchd unit, uninstalls the pip package, removes symlinks, strips the source line from tmux.conf, and optionally cleans up config, cache, and repo directories.

## Architecture

### System Overview

```
+---------------------+           +----------------------------+
|   claude.ai         |           |  Claude Code process       |
|   /api/usage        |           |  (statusLine hook)         |
+--------+------------+           +-------------+--------------+
         |                                      |
    HTTPS (curl_cffi)                     stdin JSON
         |                                      |
+--------v------------+           +-------------v--------------+
|  tmux-status-server |           | tmux-status-context-hook.js|
|  (Python/Bottle)    |           | (Node.js)                  |
|  - scraper.py       |           +-------------+--------------+
|  - server.py        |                         |
|  port 7850          |               atomic write (tmp+rename)
+--------+------------+                         |
         |                        +-------------v--------------+
    HTTP GET /quota               | ~/.cache/tmux-status/      |
         |                        | claude-ctx-{sessionId}.json|
+--------v-----------------+      +-------------+--------------+
| tmux-claude-status       |                    |
| (Bash + embedded Python) |<------- read ------+
| - renders status line 0  |
| - HTTP fetch + disk cache|
+--------+-----------------+
         |
   tmux status-format[0]
         |
+--------v------------+
|  tmux status bar     |
|  Line 0: Claude info |
|  Line 1: git status  |
|  Line 2: window tabs  |
+-----------------------+
```

### Component Responsibilities

| Component | Language | Role |
|-----------|----------|------|
| `server/tmux_status_server/server.py` | Python | HTTP server with `/quota` and `/health` endpoints, background poll thread, signal handling |
| `server/tmux_status_server/scraper.py` | Python | Scrapes claude.ai for quota data using `curl_cffi`, validates session key files |
| `server/tmux_status_server/config.py` | Python | CLI argument parsing with `argparse`, security warnings for exposed binds |
| `scripts/tmux-claude-status` | Bash/Python | Renders status line 0; finds Claude session, reads transcript, fetches quota from server |
| `scripts/tmux-git-status` | Bash | Renders status line 1; shows path, branch, dirty state, ahead/behind |
| `scripts/tmux-status-context-hook.js` | Node.js | Claude Code `statusLine` hook; writes context window usage to bridge files |
| `scripts/tmux-status-apply-config` | Bash | Applies `settings.conf` options (clock format, top banner) to tmux |
| `scripts/tmux-status-session` | Bash/Python | Creates tmux sessions from `windows.json` config |
| `overlay/status.conf` | tmux conf | Defines the 3-line status bar layout, window styling, activity monitoring |

### Data Flow

**Quota data path:**
1. `tmux-status-server` starts a background thread that calls `scraper.fetch_quota()` every `--interval` seconds (default: 300s)
2. The scraper calls `claude.ai/api/organizations` to discover the org UUID (cached after first call), then `claude.ai/api/organizations/{uuid}/usage` for quota data
3. The server caches the result in memory (`_cached_data`)
4. Every 5 seconds, tmux invokes `tmux-claude-status` via `#(...)` shell expansion
5. The renderer's embedded Python calls `urllib.request.urlopen()` against `QUOTA_SOURCE` (default: `http://127.0.0.1:7850`)
6. The response is validated and written atomically to the local disk cache (`~/.cache/tmux-status/claude-quota.json`)
7. If the HTTP fetch fails, the renderer reads stale data from the disk cache (silent failure)

**Context data path:**
1. Claude Code invokes the `statusLine` hook on every context window update
2. `tmux-status-context-hook.js` receives JSON on stdin with `session_id` and `context_window`
3. The hook normalizes autocompact (16.5% reserved buffer), writes atomic JSON to `~/.cache/tmux-status/claude-ctx-{sessionId}.json`
4. The renderer reads this bridge file to display context percentage

## API Reference

The server exposes two endpoints. All responses have `Content-Type: application/json`.

### GET /quota

Returns the most recent quota data scraped from claude.ai.

**Authentication:** Required when `--api-key-file` is configured. Send the key in the `X-API-Key` header.

**Success response (200):**

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

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"ok"` on success |
| `org_uuid` | string | Claude organization UUID |
| `five_hour` | object | 5-hour rolling window quota |
| `five_hour.utilization` | number or `"X"` | Usage percentage (0-100), or `"X"` on error |
| `five_hour.resets_at` | string or null | ISO 8601 reset time |
| `seven_day` | object | 7-day rolling window quota |
| `seven_day.utilization` | number or `"X"` | Usage percentage (0-100), or `"X"` on error |
| `seven_day.resets_at` | string or null | ISO 8601 reset time |
| `timestamp` | integer | Unix epoch when data was fetched |

**Starting response (503) -- no data yet:**

Returned when the server has started but the first scrape has not completed.

```json
{
  "status": "starting",
  "five_hour": {"utilization": "X", "resets_at": null},
  "seven_day": {"utilization": "X", "resets_at": null},
  "timestamp": 1743696000,
  "error": "no_data_yet"
}
```

**Error response (200, non-ok status):**

When scraping fails, the server returns 200 with an error status. The renderer uses the `status` field to determine display behavior.

```json
{
  "status": "session_key_expired",
  "five_hour": {"utilization": "X", "resets_at": null},
  "seven_day": {"utilization": "X", "resets_at": null},
  "timestamp": 1743696000,
  "error": "session_key_expired"
}
```

Error status codes:

| `status` value | Cause |
|----------------|-------|
| `session_key_expired` | HTTP 401 from claude.ai -- session key invalid or expired |
| `blocked` | HTTP 403 from claude.ai -- request blocked |
| `rate_limited` | HTTP 429 from claude.ai -- rate limit hit |
| `upstream_error` | Any other HTTP error or network failure |
| `no_key` | Session key file missing or unreadable |
| `insecure_permissions` | Session key file readable by group/other (must be 0600/0400) |
| `invalid_json` | Session key file contains invalid JSON or missing `sessionKey` field |

**Authentication failure (401):**

When `--api-key-file` is configured and the request has no or wrong `X-API-Key` header.

> **Known issue (TS-40):** The 401 response body is rendered as HTML by Bottle's default error handler, not JSON. A `@app.error(401)` handler is needed to match the JSON contract. See Known Issues.

### GET /health

Returns server health status. Not gated by API key authentication.

**Response (200):**

```json
{
  "status": "ok",
  "uptime_seconds": 3600,
  "version": "0.1.0"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"ok"` (data cached, last scrape succeeded), `"degraded"` (data cached but last scrape failed), or `"error"` (no data cached yet) |
| `uptime_seconds` | integer | Seconds since server started |
| `version` | string | Server package version |

### Error Responses

| Status Code | Response | Condition |
|-------------|----------|-----------|
| 401 | `{"error": "invalid_or_missing_api_key"}` | Missing or wrong API key (when auth configured) |
| 404 | `{"error": "not_found"}` | Unknown endpoint |
| 500 | `{"error": "internal_error"}` | Unhandled server error |

## Configuration

### settings.conf

Located at `~/.config/tmux-status/settings.conf`. Sourced as shell variables by the renderer.

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `CLOCK_24H` | boolean | `false` | Use 24-hour clock format in the status bar |
| `SHOW_TOP_BANNER` | boolean | `true` | Show hostname banner at top of each pane |
| `TOP_BANNER_COLOR` | integer | `208` | 256-color code for the top banner (orange) |
| `QUOTA_SOURCE` | URL | `http://127.0.0.1:7850` | URL of the quota data server |
| `QUOTA_API_KEY` | string | (empty) | API key for authenticating with the server |
| `QUOTA_CACHE_TTL` | integer | `0` | Cache TTL in seconds. `0` = always fetch (localhost). `30` = recommended for remote servers |
| `QUOTA_REFRESH_PERIOD` | integer | `300` | **Deprecated.** Use server's `--interval` flag instead |
| `QUOTA_DATA_PATH` | path | `~/.cache/tmux-status/claude-quota.json` | **Deprecated.** Path to quota bridge file |

After editing, reload tmux config:

```bash
tmux source-file ~/.config/tmux/tmux.conf
```

### Server CLI Flags

The `tmux-status-server` command accepts:

| Flag | Default | Description |
|------|---------|-------------|
| `--host` | `127.0.0.1` | Bind address. Use `0.0.0.0` for multi-machine setups |
| `--port` | `7850` | Bind port |
| `--key-file` | `~/.config/tmux-status/claude-usage-key.json` | Path to session key JSON |
| `--api-key-file` | None | Path to file containing API key for client auth |
| `--interval` | `300` | Scrape interval in seconds (minimum: 30) |
| `--log-level` | `INFO` | Logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |

**Security warning:** When binding to a non-localhost address without `--api-key-file`, the server logs a warning: `"WARNING: Listening on <host>:<port> with NO authentication."` Configure an API key for any network-accessible deployment.

### Session Key File

`~/.config/tmux-status/claude-usage-key.json`:

```json
{
  "sessionKey": "sk-ant-sid01-...",
  "expiresAt": "2026-05-01T00:00:00Z"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `sessionKey` | Yes | Claude.ai session cookie value |
| `expiresAt` | No | ISO 8601 expiry timestamp. Enables 24-hour expiry warning (red text in status bar) |

**Permissions:** Must be `0600` or `0400` (owner-only read/write). The server rejects files with group or other permissions set.

### Signal Handling

The running server process responds to Unix signals:

| Signal | Behavior |
|--------|----------|
| `SIGTERM` | Clean shutdown (exit 0) |
| `SIGINT` | Clean shutdown (exit 0) |
| `SIGUSR1` | Trigger immediate scrape (wakes the poll thread) |

Example: Force an immediate quota refresh:

```bash
kill -USR1 $(pgrep -f tmux-status-server)
```

## Deployment

### Single-Machine Setup (Default)

The installer handles this automatically. The server binds to `127.0.0.1:7850` and the renderer fetches from the same address.

```
settings.conf:
  QUOTA_SOURCE=http://127.0.0.1:7850
  QUOTA_CACHE_TTL=0

server flags: (defaults are fine)
  tmux-status-server
```

With `QUOTA_CACHE_TTL=0`, the renderer fetches from the server on every 5-second tmux refresh cycle. This is efficient on localhost (sub-millisecond latency).

### Multi-Machine Setup (LAN/Tailscale)

Run the server on one machine. All other machines point their `QUOTA_SOURCE` at it.

**Server machine:**

```bash
# Generate an API key
openssl rand -hex 32 > ~/.config/tmux-status/api.key
chmod 600 ~/.config/tmux-status/api.key

# Start server on all interfaces with auth
tmux-status-server --host 0.0.0.0 --api-key-file ~/.config/tmux-status/api.key
```

To make this persistent, edit the systemd unit or launchd plist to add the extra flags. For systemd:

```ini
# ~/.config/systemd/user/tmux-status-server.service
[Service]
ExecStart=%h/.local/bin/tmux-status-server --host 0.0.0.0 --api-key-file %h/.config/tmux-status/api.key
```

Then `systemctl --user daemon-reload && systemctl --user restart tmux-status-server`.

**Client machines:**

Edit `~/.config/tmux-status/settings.conf`:

```bash
QUOTA_SOURCE=http://server-hostname:7850
QUOTA_API_KEY=<paste the contents of api.key from the server>
QUOTA_CACHE_TTL=30
```

With `QUOTA_CACHE_TTL=30`, the renderer uses the local disk cache for 30 seconds between HTTP fetches, reducing network traffic.

Client machines do not need `curl_cffi`, a session key, or the server package running locally. They only need the base tmux-status scripts.

### Docker

The server ships with a Dockerfile at `server/Dockerfile`.

```bash
cd ~/projects/tmux-status/server

# Build
docker build -t tmux-status-server .

# Run (mount the session key file)
docker run -d \
  --name tmux-status-server \
  -p 7850:7850 \
  -v ~/.config/tmux-status/claude-usage-key.json:/app/key.json:ro \
  tmux-status-server \
  --host 0.0.0.0 \
  --key-file /app/key.json
```

The Dockerfile:
- Uses `python:3.12-slim` as the base image
- Runs as a non-root user (`appuser` created via `useradd -r`)
- Exposes port 7850
- Default CMD binds to `0.0.0.0` (required for Docker port mapping)

To add API key authentication in Docker:

```bash
docker run -d \
  --name tmux-status-server \
  -p 7850:7850 \
  -v ~/.config/tmux-status/claude-usage-key.json:/app/key.json:ro \
  -v ~/.config/tmux-status/api.key:/app/api.key:ro \
  tmux-status-server \
  --host 0.0.0.0 \
  --key-file /app/key.json \
  --api-key-file /app/api.key
```

### systemd (Linux)

The installer copies `server/deploy/tmux-status-server.service` to `~/.config/systemd/user/` and enables it.

Service file contents:

```ini
[Unit]
Description=tmux-status quota server
After=network.target

[Service]
ExecStart=%h/.local/bin/tmux-status-server
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

Management commands:

```bash
systemctl --user status tmux-status-server
systemctl --user restart tmux-status-server
systemctl --user stop tmux-status-server
journalctl --user -u tmux-status-server -f  # view logs
```

Note: This is a **user** unit (not system), so it runs as your user and does not require root.

### launchd (macOS)

The installer copies `server/deploy/io.mikey.tmux-status-server.plist` to `~/Library/LaunchAgents/` and loads it.

Management commands:

```bash
launchctl list | grep tmux-status-server
launchctl unload ~/Library/LaunchAgents/io.mikey.tmux-status-server.plist
launchctl load ~/Library/LaunchAgents/io.mikey.tmux-status-server.plist
```

The plist sets `RunAtLoad` and `KeepAlive` to `true`, so the server starts on login and restarts if it crashes.

## Development

### Project Structure

```
tmux-status/
  overlay/
    status.conf              # tmux overlay (sourced by user's tmux.conf)
  scripts/
    tmux-claude-status       # Line 0 renderer (Bash + embedded Python)
    tmux-git-status          # Line 1 renderer (Bash)
    tmux-status-apply-config # Config applier (Bash)
    tmux-status-session      # Session launcher (Bash + Python)
    tmux-status-context-hook.js  # Claude Code statusLine hook (Node.js)
  server/
    tmux_status_server/
      __init__.py            # Package version (0.1.0)
      __main__.py            # Entry point for python -m
      server.py              # QuotaServer class, HTTP endpoints, poll thread
      scraper.py             # claude.ai scraping, session key validation
      config.py              # CLI argument parsing
    deploy/
      tmux-status-server.service         # systemd unit
      io.mikey.tmux-status-server.plist  # launchd plist
    tests/
      test_config.py         # CLI argument parsing tests
      test_scraper.py        # Scraper and session key tests
      test_server.py         # Server endpoint, auth, poll thread, signal tests
      test_deploy.py         # Deployment file validation tests
      test_package.py        # Package structure and entry point tests
      test_validate_cycle3.py  # Validation cycle 3 tests
      test_validate_cycle5.py  # Fix cycle 5 regression tests
      test_validate_gaps.py    # Gap coverage tests
    Dockerfile               # Container image
    pyproject.toml           # Python package config
  config/
    settings.example.conf    # Default settings template
    windows.example.json     # Session launcher example
  install.sh                 # Installer
  uninstall.sh               # Uninstaller
```

### Running Tests

```bash
cd ~/projects/tmux-status/server
python3 -m pytest tests/ -v
```

All tests use Python's `unittest` framework (discovered by pytest). External dependencies (`bottle`, `curl_cffi`) are mocked in tests -- you can run the test suite without them installed.

### Key Development Conventions

- **Atomic writes:** All bridge/cache files use temp-file + `os.replace()` (Python) or `fs.renameSync()` (Node.js) to avoid partial reads.
- **Silent failure:** Scripts exit 0 and output nothing when data is unavailable. The status bar should never show errors -- it should show nothing.
- **Lazy imports:** `bottle` is imported inside `QuotaServer._create_app()`, not at module level. `curl_cffi` is imported inside `scraper._http_get()`. This keeps module-level imports stdlib-only.
- **No raw exception text:** Error dicts returned by the scraper contain machine-readable codes (`session_key_expired`, `blocked`, `upstream_error`, etc.), never Python exception messages or tracebacks.
- **Reference swap for thread safety:** `_cached_data` is updated via simple reference assignment (Python's GIL makes this atomic), not `threading.Lock`.

### Adding a New Endpoint

1. Add a route in `QuotaServer._create_app()` using `@app.route("/path")`
2. Set `response.content_type = "application/json"` and return `json.dumps(...)`
3. If the endpoint should require auth, do not add an exemption in `check_auth`
4. Add tests in `test_server.py`

### Adding a New Config Option

1. Add the default in `settings.example.conf` with a comment
2. Parse it in the embedded Python block of `tmux-claude-status` (the `_settings_file` loop)
3. Document it in this file and the README

## Architecture Decision Records

### ADR-001: Server Always Present (No Dual-Mode)

**Status:** Accepted

**Context:** The old quota system used standalone scripts (`tmux-status-quota-fetch` + `tmux-status-quota-poll`). The question was whether to support both direct scraping (legacy mode) and server-based fetching, or require the server for all quota access.

**Decision:** The server is always present. The renderer always fetches quota via HTTP, even on single-machine setups where the server runs on localhost. The legacy `tmux-status-quota-fetch` and `tmux-status-quota-poll` scripts were deleted.

**Consequences:**
- Simpler renderer code -- one code path (HTTP fetch) instead of two (HTTP fetch vs. direct scrape)
- Installation is slightly heavier (pip package + daemon), but the installer handles this automatically
- `curl_cffi` is only needed on the server machine, not every client
- Multi-machine deployment is trivial -- just change `QUOTA_SOURCE` in settings.conf
- Localhost overhead is negligible (sub-millisecond HTTP on loopback)

### ADR-002: Bottle as HTTP Framework

**Status:** Accepted

**Context:** Needed a lightweight HTTP server. Options considered: stdlib `http.server`, Flask, Bottle, FastAPI/Uvicorn.

**Decision:** Bottle. Single-file dependency, no external requirements beyond the package itself, sufficient for two endpoints.

**Consequences:**
- Minimal dependency footprint (one package, no transitive dependencies)
- Lazy import pattern keeps module-level imports stdlib-only
- No async support, but not needed for this use case (two endpoints, background thread for scraping)
- Bottle's default error handler renders HTML, which caused the TS-40 issue (401 responses are HTML not JSON)

### ADR-003: Client-Side Disk Cache with TTL

**Status:** Accepted

**Context:** The renderer runs every 5 seconds (tmux `status-interval`). Fetching from the server on every cycle is fine on localhost but wasteful over a network.

**Decision:** The renderer maintains a local disk cache at `~/.cache/tmux-status/claude-quota.json`. The `QUOTA_CACHE_TTL` setting controls how long the cache is considered fresh. Default is `0` (always fetch) for localhost, recommended `30` for remote servers.

**Consequences:**
- Localhost deployments see near-real-time quota data (fetch every 5s)
- Remote deployments see data up to `TTL` seconds stale, but save network round-trips
- If the server goes down, the renderer silently falls back to stale cached data
- Atomic writes prevent partial reads of the cache file

### ADR-004: API Key Authentication via X-API-Key Header

**Status:** Accepted

**Context:** Multi-machine deployments expose the server on a network. The server holds a claude.ai session key, so unauthorized access means quota data leakage.

**Decision:** Optional API key authentication via the `X-API-Key` HTTP header. Key is stored in a file (`--api-key-file`), read on startup. Comparison uses `hmac.compare_digest()` for timing-safe comparison. The `/health` endpoint is exempt from auth (monitoring should work without credentials).

**Consequences:**
- Simple to set up (`openssl rand -hex 32 > api.key`)
- No user management, sessions, or tokens -- single shared key
- Key file must be distributed to client machines (via the `QUOTA_API_KEY` setting)
- No transport encryption (HTTP, not HTTPS) -- relies on network-level security (Tailscale, VPN, or trusted LAN). Adding TLS would require certificate management.

### ADR-005: Minimum 30-Second Scrape Interval

**Status:** Accepted

**Context:** The `--interval` flag controls how often the server scrapes claude.ai. Very low values risk rate limiting or IP blocking.

**Decision:** The server rejects `--interval` values below 30 seconds with a parser error.

**Consequences:**
- Prevents accidental abuse of claude.ai's API
- Default of 300 seconds (5 minutes) is conservative and suitable for most use cases
- Users who need faster updates can set 30 seconds, but no lower
- The `SIGUSR1` signal provides an escape hatch for on-demand immediate scrapes

## Known Issues

### ESCALATE: TS-39 -- $TRANSCRIPT Shell Interpolation in Python Heredoc

**Severity:** Important (theoretical risk)

The renderer (`scripts/tmux-claude-status`) uses an unquoted heredoc (`<< PYEOF`) at line 46 that interpolates the `$TRANSCRIPT` shell variable directly into the embedded Python code. While fix cycle 5 (TS-33) eliminated `$pidfile` interpolation by switching to `sys.argv`, the same heredoc still interpolates `$TRANSCRIPT` into a Python string at line 49.

**Practical risk:** Low. Claude Code names JSONL transcript files using UUIDs, making crafted filenames essentially impossible in normal use.

**Recommended fix:** Either quote the heredoc (`<< 'PYEOF'`) and pass `$TRANSCRIPT` via `sys.argv[2]` or environment variable, or accept as documented risk given the UUID filename constraint.

### ESCALATE: TS-40 -- 401 Response is HTML Not JSON

**Severity:** Important (API contract violation)

When API key authentication fails, `abort(401, ...)` returns HTML because Bottle's default error handler renders HTML. The server has custom `@app.error(404)` and `@app.error(500)` handlers that return JSON, but no `@app.error(401)` handler.

**Practical impact:** Low. The renderer checks HTTP status codes, not response bodies. Only affects direct API consumers that parse 401 response bodies.

**Recommended fix:** Add a `@app.error(401)` handler matching the existing 404/500 pattern (3-line change).

### Deferred Advisories

| Item | Severity | Description |
|------|----------|-------------|
| README references deleted legacy scripts | Useful | README still mentions `tmux-status-quota-fetch` and `tmux-status-quota-poll` which were deleted. Users following old README instructions will get "command not found" |
| uninstall.sh dead entries in SCRIPTS array | Useful | `uninstall.sh` SCRIPTS array still lists `tmux-status-quota-fetch` and `tmux-status-quota-poll`. Harmless -- the symlink check (`[ -L "$dst" ]`) gracefully skips non-existent entries |
| settings.conf sourced as shell code | Useful | `settings.conf` is sourced as shell code by `tmux-status-apply-config`. This is standard shell convention (like `.bashrc`) for a user-owned config file |

## Test Coverage

### Summary

**406 tests passing** across 8 test files.

### Coverage by Area

| Test File | Tests | What It Covers |
|-----------|-------|----------------|
| `test_config.py` | CLI defaults, custom values, tilde expansion, interval validation (min 30), log level validation, `warn_if_exposed` for localhost/non-localhost/IPv6 |
| `test_scraper.py` | Session key reading (valid, missing, bad permissions, invalid JSON), quota fetching (success, HTTP errors 401/403/429/500, network errors, empty orgs), org UUID caching/reset on auth errors, request headers, no raw exception text in errors |
| `test_server.py` | Server module structure (AST-verified), QuotaServer init, `/quota` endpoint (503 starting, 200 success, error passthrough), `/health` endpoint (ok/degraded/error states, version, uptime), auth hook (no key, missing header, wrong key, correct key, health exemption, hmac.compare_digest), background poll (immediate scrape, key re-read, key error, fetch exception), signal handling (SIGTERM/SIGINT/SIGUSR1), API key file loading |
| `test_deploy.py` | systemd unit (sections, ExecStart, Restart, WantedBy), launchd plist (valid XML, Label, ProgramArguments, RunAtLoad, KeepAlive), Dockerfile (base image, pip install, EXPOSE, ENTRYPOINT/CMD, WORKDIR, non-root USER) |
| `test_package.py` | `__init__.py` version, `__main__.py` structure and delegation, pyproject.toml contents, module runnability |
| `test_validate_cycle3.py` | Earlier validation cycle coverage |
| `test_validate_cycle5.py` | TS-31 (status code case pattern), TS-33 (sys.argv pidfile), TS-32 (Dockerfile USER), TS-34 (context hook atomic writes), TS-35 (legacy script removal), TS-37 (interval boundary edge cases), script syntax validation, renderer error status consistency |
| `test_validate_gaps.py` | Gap coverage from validation passes |

### What Is Not Covered

- **Integration tests:** No tests start an actual Bottle server and make real HTTP requests. All server tests use mocked Bottle.
- **End-to-end tests:** No tests exercise the full path from tmux invoking `tmux-claude-status` through HTTP fetch to status bar output.
- **Shell script unit tests:** The Bash scripts (`tmux-claude-status`, `tmux-git-status`) are tested only for syntax validity and specific patterns (AST/regex). No tests verify their output given specific inputs.
- **Context hook tests:** `tmux-status-context-hook.js` is tested for atomic write patterns and syntax, but not for correct context percentage calculation.
- **TLS/HTTPS:** No transport encryption support; relies on network-level security.
- **401 response body format:** Not tested (see TS-40 known issue).

### Running Tests

```bash
cd ~/projects/tmux-status/server
python3 -m pytest tests/ -v

# Run a specific test file
python3 -m pytest tests/test_server.py -v

# Run a specific test class
python3 -m pytest tests/test_config.py::TestIntervalLowerBound -v
```
