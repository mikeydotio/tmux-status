# Handoff: Design → Plan

## Timestamp
2026-04-03T14:30:00Z

## Artifacts Produced
- `.forge/DESIGN.md` — Full architecture design, approved by user

## Key Decisions

1. **Server is always present** — no standalone poller mode. The server replaces `tmux-status-quota-fetch` and `tmux-status-quota-poll`. For single-machine installs, server runs on `127.0.0.1:7850`. For multi-machine, on a remote host.

2. **Server is canonical scraper** — scraping logic lives in `server/tmux_status_server/scraper.py` only. Old scripts are deprecated. No code duplication.

3. **`QUOTA_SOURCE` always set** — defaults to `http://127.0.0.1:7850` for standard installs. Renderer always fetches via HTTP.

4. **`QUOTA_CACHE_TTL` configurable** — 0s default for localhost (always fetch, 1-5ms), 30s for remote setups. Disk cache serves as fallback when server unreachable.

5. **Error signaling with "X" values** — server returns `"utilization": "X"` on error conditions (expired key, blocked, etc.). Renderer displays `X%` in status bar.

6. **Default bind `127.0.0.1`** — safe default, explicit `--host` required for network exposure.

7. **Platform-specific daemons** — systemd user unit on Linux, launchd plist on macOS. install.sh detects OS.

8. **API key via file** — `--api-key-file` preferred over CLI flags or env vars. `hmac.compare_digest()` for comparison.

9. **Key file permission enforcement** — server refuses to start if `claude-usage-key.json` is world-readable.

10. **Error sanitization** — generic error codes in API responses, never raw exceptions.

## Context for Next Step

### Components to Implement
1. **`server/` package** (~290 lines): `config.py`, `scraper.py`, `server.py`, `__init__.py`, `__main__.py`, `pyproject.toml`, Dockerfile, systemd unit, launchd plist
2. **`tmux-claude-status` modification** (~25 lines): add HTTP fetch + cache logic before existing bridge-file read
3. **`settings.conf` update**: add `QUOTA_SOURCE`, `QUOTA_API_KEY`, `QUOTA_CACHE_TTL`; remove `QUOTA_DATA_PATH`, `QUOTA_REFRESH_PERIOD`
4. **`install.sh` modification**: add `pip install ./server/`, daemon setup, OS detection
5. **`uninstall.sh` modification**: add daemon teardown, server uninstall
6. **`.gitignore` creation**: security-related exclusions

### Interface Contracts
- `GET /quota` → bridge-format JSON (status, five_hour, seven_day, timestamp)
- `GET /health` → minimal status JSON (status, uptime, version)
- Error conditions: `utilization: "X"`, `status: "<error_code>"`
- Auth: `X-API-Key` header, `hmac.compare_digest()`, `/health` exempt

### Security Requirements
- Key file `chmod 600` check at startup
- Startup warning on non-localhost bind without auth
- Error sanitization (no raw exceptions in responses)
- `bottle>=0.12.25` pinning (CVE fix)
- `.gitignore` with credential patterns

### Complexity Areas
- `scraper.py`: extracting from `tmux-status-quota-fetch` (org discovery, curl_cffi impersonation, session key parsing)
- `install.sh`: OS detection, daemon install for both Linux and macOS
- Backward compatibility: `QUOTA_DATA_PATH` still honored if set, old poller scripts left in place but deprecated

### Inter-Component Dependencies
- Server must be installed before renderer can fetch from it
- Daemon must be running before tmux renders quota data
- `settings.conf` must have `QUOTA_SOURCE` set (install.sh handles default)

## Pipeline State
- Fix cycle: 0 / 3
- Yolo mode: false
- Team roster: software-architect, security-researcher, devils-advocate (all active), ux-designer (skipped), accessibility-engineer (skipped)
- ESCALATE stories pending: 0

## Open Questions for Planning
- Should deprecated scripts be removed or left with a deprecation notice?
- How to handle existing installations that have `QUOTA_REFRESH_PERIOD` set?
- Should the Dockerfile be included in v1 or deferred?
- Testing strategy — the project has no test suite, but the server handles credentials and serves a network API. Minimum viable testing?
