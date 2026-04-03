# Architecture Design

## System Overview

A lightweight REST API server (~300 lines Python) that replaces the standalone quota polling daemon. The server is **always present** — for single-machine installs it runs on localhost, for multi-machine setups it runs on a remote host. The renderer always fetches quota data via HTTP from the server. There is no "standalone mode" vs "client mode" — only one architecture.

```
                      SINGLE-MACHINE INSTALL
                      ══════════════════════

  ┌──────────────┐       ┌──────────────────────────────────┐
  │  claude.ai   │◄──────│  tmux-status-server              │
  │  (upstream)  │──────►│  (systemd/launchd, 127.0.0.1)    │
  └──────────────┘       │  scrapes → in-memory cache       │
                         │  GET /quota, GET /health :7850    │
                         └────────────┬─────────────────────┘
                                      │ localhost HTTP
                                      ▼
                         ┌──────────────────────────────────┐
                         │  tmux-claude-status (renderer)   │
                         │  fetch → disk cache → render     │
                         │  QUOTA_SOURCE=http://127.0.0.1:7850
                         │  QUOTA_CACHE_TTL=0               │
                         └──────────────────────────────────┘


                      MULTI-MACHINE SETUP
                      ═══════════════════

  ┌──────────────┐       ┌──────────────────────────────────┐
  │  claude.ai   │◄──────│  tmux-status-server (Host A)     │
  │  (upstream)  │──────►│  --host 0.0.0.0 --api-key-file …│
  └──────────────┘       │  scrapes → in-memory cache       │
                         └────────────┬─────────────────────┘
                                      │ LAN / Tailscale HTTP
                        ┌─────────────┼─────────────┐
                        ▼             ▼             ▼
                   ┌─────────┐  ┌─────────┐  ┌─────────┐
                   │Client B │  │Client C │  │Client D │
                   │TTL=30s  │  │TTL=30s  │  │TTL=30s  │
                   │fetch →  │  │fetch →  │  │fetch →  │
                   │cache →  │  │cache →  │  │cache →  │
                   │render   │  │render   │  │render   │
                   └─────────┘  └─────────┘  └─────────┘
```

Key insight: the renderer always reads from a disk cache file. It always attempts an HTTP fetch (subject to TTL), writes the response to the cache on success, and falls back to stale cache on failure. The rendering code path is identical regardless of whether the server is local or remote.

## Components

### tmux-status-server (new package)

- **Purpose:** Scrape claude.ai for quota data and serve it via HTTP REST API
- **Interfaces:** `GET /quota`, `GET /health` on configurable host:port (default `127.0.0.1:7850`)
- **Dependencies:** `bottle>=0.12.25`, `curl_cffi>=0.5`, Python `>=3.10`
- **Key decisions:** Server is the canonical owner of all scraping logic. The old `tmux-status-quota-fetch` and `tmux-status-quota-poll` scripts are deprecated and replaced by this package.

### tmux-claude-status (modified)

- **Purpose:** Render tmux status line 0 (unchanged); fetch quota data from server (new)
- **Interfaces:** Called by tmux via `#(tmux-claude-status <pane_pid>)` every 5 seconds
- **Dependencies:** stdlib `urllib.request` for HTTP fetch (no new external deps)
- **Key decisions:** Always fetches from `QUOTA_SOURCE` URL. Disk cache at `~/.cache/tmux-status/claude-quota.json` serves as fallback when server is unreachable. `QUOTA_CACHE_TTL` controls fetch frequency (0s for localhost = always fetch, 30s for remote).

### install.sh (modified)

- **Purpose:** Install tmux-status including the server package and platform-specific daemon
- **Interfaces:** `./install.sh` (interactive) 
- **Dependencies:** `pip` for server install, `systemctl` (Linux) or `launchctl` (macOS) for daemon
- **Key decisions:** Detects OS, installs appropriate daemon config (systemd user unit on Linux, launchd plist on macOS). Sets `QUOTA_SOURCE=http://127.0.0.1:7850` in default `settings.conf`.

## Data Flow

### Render Cycle (every 5 seconds)

```
1. tmux fires #(tmux-claude-status <pane_pid>)
2. Script finds Claude session, parses transcript for model/effort
3. Script reads settings.conf → gets QUOTA_SOURCE, QUOTA_CACHE_TTL
4. If QUOTA_CACHE_TTL > 0: check cache file mtime
   - If age < TTL → skip fetch, read cache
   - If age >= TTL or file missing → proceed to fetch
   If QUOTA_CACHE_TTL == 0: always proceed to fetch
5. HTTP GET {QUOTA_SOURCE}/quota (3s timeout, X-API-Key header if configured)
6. On success → atomic-write response to cache file → read cache
   On failure → read stale cache file (if exists)
   On stale cache > 30 min or missing → hide quota section
7. If utilization values are "X" → render "X%" to signal error condition
8. Output formatted tmux string
```

### Server Scrape Cycle

```
1. Background thread wakes after --interval seconds (default 300)
2. Calls scraper.fetch()
3. Scraper reads session key from --key-file
4. Scraper discovers org UUID (cached after first discovery)
5. Scraper fetches usage from claude.ai via curl_cffi
6. On success → stores bridge-format dict in memory
   On failure → sets error status with "X" utilization values
7. Thread sleeps, HTTP requests continue serving cached data
```

### Error Signaling

When the server encounters an error condition, it returns the response with `"X"` string values for utilization instead of numbers. The renderer displays these as-is (e.g., `X%`), signaling to the user that something is wrong without breaking the tmux format string.

| Server Condition | `status` field | `utilization` value |
|-----------------|---------------|-------------------|
| Normal | `"ok"` | Integer 0-100 |
| Session key expired | `"expired"` | `"X"` |
| Blocked by Cloudflare | `"blocked"` | `"X"` |
| Rate limited | `"rate_limited"` | `"X"` |
| No session key file | `"no_key"` | `"X"` |
| Upstream fetch error | `"upstream_error"` | `"X"` |
| No data yet (first startup) | `"starting"` | `"X"` |

The `error` field contains a machine-readable error code (never raw exception text). Users who see `X%` in their status bar can `curl http://127.0.0.1:7850/health` to diagnose.

## Interface / API Design

### `GET /quota`

Returns quota data in the bridge JSON format.

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

**Error condition (200 — error is in the data, not the HTTP status):**
```json
{
  "status": "expired",
  "five_hour": {
    "utilization": "X",
    "resets_at": null
  },
  "seven_day": {
    "utilization": "X",
    "resets_at": null
  },
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

All responses are `Content-Type: application/json`.

### `GET /health`

Monitoring endpoint. Always returns 200. Not gated by API key auth.

```json
{
  "status": "ok",
  "uptime_seconds": 3600,
  "version": "0.1.0"
}
```

`status` values: `"ok"` (last scrape succeeded), `"degraded"` (has cached data but last scrape failed), `"error"` (no data at all).

### Authentication

When `--api-key-file` is provided:
- `/quota` requires `X-API-Key` header matching the file contents
- Comparison uses `hmac.compare_digest()` (timing-safe)
- Missing or wrong key returns 401
- `/health` is exempt

When no API key configured: all endpoints open, no headers checked.

## Cross-Cutting Concerns

### Logging (Server)
- Python `logging` module to stdout only
- Format: `%(asctime)s %(levelname)s %(message)s`
- Default level: `INFO`, configurable via `--log-level`
- INFO events: startup config summary, each scrape result, shutdown
- DEBUG events: individual HTTP requests (Bottle default logging)

### Logging (Client)
- None. Renderer produces zero output beyond the tmux format string. Errors are silent.

### Error Handling

**Server scraper:** Catch all exceptions in the poll thread. Log the error. Set error status with `"X"` utilization values. Never include raw exception text in responses — use generic error codes only.

**Server HTTP:** Bottle handles malformed requests. Unknown routes return 404. Route handler exceptions return 500 with `{"error": "internal_error"}`.

**Client fetch:** Catch all exceptions from `urllib.request`. On any failure, fall through to stale disk cache. No retry, no logging, no error output.

### Signal Handling (Server)

| Signal | Behavior |
|--------|----------|
| `SIGTERM` | Set shutdown flag, stop poll thread, stop Bottle server. Exit 0. |
| `SIGINT` | Same as SIGTERM. |
| `SIGUSR1` | Wake poll thread for immediate out-of-cycle scrape. |

### Atomic Writes

Client disk cache uses temp-file + `os.replace()`:
```python
tmp = cache_path + ".tmp"
with open(tmp, "w") as f:
    f.write(response_body)
os.replace(tmp, cache_path)
```

### Thread Safety (Server)

Two threads: Bottle HTTP (main) + scraper poll (background). Shared state is the cached data dict. Reference swap via `self._cached_data = new_data` is atomic under GIL. No lock needed. Worst case is a single stale read during swap — acceptable for quota data.

## Security Considerations

### Credential Protection

1. **Session key file permissions:** Server checks `claude-usage-key.json` is `chmod 600` at startup. Refuses to start with a clear error if world-readable. Config directory should be `700`.

2. **No credentials in responses:** `/quota` returns only derived data (utilization percentages, timestamps). The session key never crosses the network boundary.

3. **Error sanitization:** Error responses use generic codes (`session_key_expired`, `upstream_error`). Raw exception messages logged to stdout only, never in API responses or cache files.

4. **API key storage:** Prefer `--api-key-file` over CLI flags (visible in `ps`) or env vars (visible in `/proc/PID/environ`). File should be `chmod 600`.

### Network Exposure

1. **Default bind `127.0.0.1`:** Server only accessible locally unless explicitly configured with `--host`.

2. **Startup warning:** When binding to non-localhost without `--api-key-file`, log: `WARNING: Listening on 0.0.0.0:7850 with NO authentication.`

3. **No TLS:** Server does not implement TLS. For remote deployments, rely on Tailscale (WireGuard encryption) or user's reverse proxy.

### Auth Implementation

- `X-API-Key` header, checked via `hmac.compare_digest()` in a Bottle `before_request` hook
- `/health` exempt from auth (monitoring needs)
- When no API key configured, no headers checked

### Repository Hygiene

`.gitignore` includes: `claude-usage-key.json`, `*.key`, `*.pem`, `.env`, `__pycache__/`, `*.pyc`

### Dependency Pinning

`bottle>=0.12.25` (CVE-2022-31799 fix in 0.12.25).

## Integration Points

### Server Replaces Standalone Poller

The scraping logic from `scripts/tmux-status-quota-fetch` is the canonical source, refactored into `server/tmux_status_server/scraper.py`. The old scripts (`tmux-status-quota-fetch`, `tmux-status-quota-poll`) are deprecated.

| Current script | Disposition |
|---------------|-------------|
| `tmux-status-quota-fetch` | Deprecated. Logic moves to `scraper.py` |
| `tmux-status-quota-poll` | Deprecated. Replaced by server's poll thread |

### Client Integration in Renderer

A ~25-line Python function inserted into `tmux-claude-status` before the existing bridge-file read:

```python
def _maybe_fetch_quota(source_url, api_key, cache_ttl, cache_path):
    """Fetch quota from server, write to disk cache. Silent on failure."""
    if not source_url:
        return
    if cache_ttl > 0:
        try:
            if time.time() - os.stat(cache_path).st_mtime < cache_ttl:
                return  # cache is fresh
        except FileNotFoundError:
            pass
    try:
        req = urllib.request.Request(source_url.rstrip('/') + '/quota')
        if api_key:
            req.add_header('X-API-Key', api_key)
        resp = urllib.request.urlopen(req, timeout=3)
        data = resp.read()
        json.loads(data)  # validate JSON
        tmp = cache_path + '.tmp'
        with open(tmp, 'wb') as f:
            f.write(data)
        os.replace(tmp, cache_path)
    except Exception:
        pass  # silent failure, use stale cache
```

### Settings.conf Changes

**New keys:**
```bash
# URL of the quota data server. Default: localhost server installed with tmux-status.
QUOTA_SOURCE=http://127.0.0.1:7850

# API key for authenticating with the quota server (optional).
# QUOTA_API_KEY=

# Cache TTL in seconds. 0 = always fetch (good for localhost). 30 = recommended for remote.
QUOTA_CACHE_TTL=0
```

**Removed keys:**
- `QUOTA_DATA_PATH` — hardcoded internally to `~/.cache/tmux-status/claude-quota.json`. Still honored if set (backward compat) but undocumented.
- `QUOTA_REFRESH_PERIOD` — replaced by server's `--interval` flag.

### Daemon Installation

`install.sh` detects the platform and installs the appropriate daemon configuration:

**Linux (systemd user unit):**
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

**macOS (launchd plist):**
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "...">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>io.mikey.tmux-status-server</string>
    <key>ProgramArguments</key>
    <array>
        <string>~/.local/bin/tmux-status-server</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
```

## Design Decisions

| Decision | Choice | Rationale | Alternatives Considered |
|----------|--------|-----------|------------------------|
| Server always present | Yes | Eliminates standalone/client mode split, single code path, no race conditions between poller and client | Dual mode (standalone poller + optional server) — rejected: two code paths, race condition on cache file |
| Server is canonical scraper | `server/scraper.py` owns all scraping logic | Single source of truth. Old scripts deprecated. When claude.ai changes API, only one codepath to update | Duplicate code (120 lines in both) — rejected: divergence risk. Shared library — rejected: over-engineering |
| Default bind `127.0.0.1` | Safe default | Prevents accidental network exposure on dual-homed machines. Users opt in with `--host` | `0.0.0.0` — rejected: too risky as default for a credential-holding service |
| `QUOTA_CACHE_TTL` configurable | 0s localhost, 30s remote | Localhost requests are 1-5ms (no caching needed). Remote requests benefit from reducing fetch frequency | Fixed TTL — rejected: different needs for local vs remote. No cache — rejected: no fallback on server downtime |
| Error signaling with "X" | `utilization: "X"` | Renderer displays `X%` in status bar, clear visual signal without breaking format. User checks `/health` for details | Numeric sentinel (-1) — rejected: could render as `-1%`. Hide section — rejected: user doesn't know something is wrong |
| Platform-specific daemons | systemd (Linux) + launchd (macOS) | Auto-start, auto-restart, proper lifecycle management. install.sh detects OS | tmux-managed — rejected: dies with tmux session. Manual — rejected: inconvenient for default install |
| HTTP framework | Bottle | Zero deps, built-in server, Flask-like API. Traffic is trivial (<10 clients) | Flask (too many deps), FastAPI (async overkill), stdlib http.server (2x code) |
| API key via file | `--api-key-file` | CLI flags visible in `ps`, env vars in `/proc`. File with `600` perms is most secure | `--api-key` CLI flag, `TMUX_STATUS_API_KEY` env var — both supported but file preferred |
| Client HTTP library | stdlib `urllib.request` | Zero new dependencies on client machines. 3s timeout sufficient | `requests` (adds dependency), `curl_cffi` (heavy, not needed for simple GET) |
| Disk cache as fallback | Always write, read on fetch failure | Graceful degradation during server restarts. Stale data > no data (up to 30 min) | No cache (hide on failure) — rejected: server restarts would cause flicker |
