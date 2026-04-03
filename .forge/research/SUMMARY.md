# Research Summary

## Key Findings

1. **Bottle is the right HTTP framework** — zero-dep micro-framework with Flask-like ergonomics. Single file, 15+ years mature, built-in server sufficient for <10 LAN clients. Matches the project's minimal-dependency philosophy. FastAPI and Flask are overkill; stdlib http.server works but requires 2x the code.

2. **Unified cache path simplifies the client** — the HTTP-fetched data writes to the same `~/.cache/tmux-status/claude-quota.json` file that the standalone poller uses. The rendering script (`tmux-claude-status`) reads the same file regardless of mode. The "client" is just a small fetch-and-cache wrapper inserted before the existing bridge-file read.

3. **mtime-based TTL is the right caching model** — each tmux render is a fresh process (no persistent HTTP client). Checking file mtime is a single `stat()` call. 60-second TTL means ~1 HTTP request per minute, ~12 cache hits per minute. Stale data gracefully degrades up to 30 minutes.

4. **pyproject.toml + console_scripts entry point** — modern packaging standard. `pip install ./server/` for local install. No PyPI needed initially. argparse for CLI flags (zero deps). Env vars + CLI flags only (skip config file).

5. **Server reuses existing scraping logic** — the quota fetching code from `tmux-status-quota-fetch` (org discovery, curl_cffi impersonation, bridge JSON format) moves into the server almost verbatim. The server adds HTTP serving and periodic background scraping.

## Existing Solutions

No existing tool solves this specific problem (sharing Claude API quota data across machines). The closest patterns:
- **Prometheus**: scrape → store → serve model (our architecture matches this)
- **collectd/telegraf**: metric collection and forwarding (heavier than needed)
- **Status bar tools (waybar/polybar)**: support custom URL-fetching scripts but have no standardized protocol

Building a custom server is the right call — the problem is too specific for an off-the-shelf tool.

## Recommended Technology Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| HTTP framework | Bottle | Zero deps, Flask-like API, built-in server |
| TLS impersonation | curl_cffi | Already used, required for Cloudflare bypass |
| CLI parsing | argparse | Stdlib, sufficient for <10 flags |
| Packaging | pyproject.toml | Modern standard, console_scripts entry point |
| Deployment | Dockerfile + systemd unit | Covers Docker and bare-metal |
| Logging | Python logging → stdout | systemd/Docker capture it |

## Patterns to Follow

1. **Atomic writes** — already established in the codebase. Server and client both use temp-file + `os.replace()`.
2. **Silent failure** — client hides quota section when server unreachable and cache is stale (>30 min). No error spam in tmux.
3. **Signal handling** — SIGTERM/SIGINT for shutdown, SIGUSR1 for immediate fetch. Same as existing poller.
4. **Unified bridge format** — server's `/quota` response is the exact same JSON as the bridge file. No translation needed.
5. **Config precedence** — CLI flags > env vars > defaults. No config file needed.

## Pitfalls to Avoid

1. **Don't use async** — curl_cffi is synchronous. Mixing async HTTP serving with sync scraping adds complexity for zero benefit at this traffic level.
2. **Don't use Alpine Docker base** — curl_cffi has C extensions that need glibc. Use `python:3.12-slim`.
3. **Don't add client-side retry logic** — the 60s cache TTL naturally rate-limits. If fetch fails, use cache, try again next TTL window.
4. **Don't add PID files** — legacy SysV pattern. systemd and Docker track processes natively.
5. **Don't over-structure the package** — this is a ~300 line server. 3-4 files max. No framework, no plugin system, no middleware stack.

## Open Questions

1. **Default port** — 7850 recommended (uncommon, memorable). Should be configurable via `--port` / `TMUX_STATUS_PORT`.
2. **Multiple session keys** — not in v1. Single key per server instance. Multi-account is a future consideration.
3. **Server scrape interval** — reuse the `QUOTA_REFRESH_PERIOD` semantics (default 300s, configurable via `--interval`).
4. **Stale data indicator** — should the rendering script show a visual hint (dimmed colors) when cache is 5-30 min old? Design decision, not a research question.
