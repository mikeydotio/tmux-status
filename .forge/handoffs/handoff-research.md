# Handoff: Research → Design

## Step Completed
research

## Key Decisions
- **HTTP framework: Bottle** — zero-dep micro-framework, built-in server, Flask-like API. Evaluated against stdlib, Flask, FastAPI, aiohttp. Bottle wins on simplicity and dep weight.
- **Client caching: mtime-based file TTL** — client writes fetched data to same path as standalone poller (`~/.cache/tmux-status/claude-quota.json`). Rendering script reads one file regardless of mode.
- **No async** — curl_cffi is synchronous, traffic is trivial. Sync Bottle server is correct.
- **Packaging: pyproject.toml + console_scripts** — `pip install ./server/`, entry point `tmux-status-server`.
- **Config: CLI flags + env vars only** — no config file. argparse for parsing.
- **Default port: 7850** — configurable via `--port` / `TMUX_STATUS_PORT`.
- **Security researcher activated** — server handles credentials (session key) and binds to network.
- **UX designer and accessibility engineer skipped** — no GUI, tmux-only output.

## Context for Next Step
### Recommended Stack
- Bottle (HTTP), curl_cffi (scraping), argparse (CLI), pyproject.toml (packaging)
- Deployment: Dockerfile (`python:3.12-slim`) + systemd unit
- Logging: Python logging → stdout

### Architecture Patterns
- Server reuses scraping logic from `tmux-status-quota-fetch` (org discovery, curl_cffi, bridge JSON format)
- Server adds: HTTP serving (Bottle), periodic background scraping (threading), optional API key auth
- Client change is minimal: small fetch-and-cache wrapper before existing bridge-file read in `tmux-claude-status`
- Unified bridge format — `/quota` returns same JSON as `claude-quota.json`

### Package Structure
```
server/
  pyproject.toml
  tmux_status_server/
    __init__.py
    __main__.py
    server.py      (Bottle app, routes, auth)
    scraper.py     (quota fetching, extracted from tmux-status-quota-fetch)
    config.py      (CLI/env config loading)
```

### Client Integration Points
- `settings.conf`: new `QUOTA_SOURCE` key (URL = client mode, unset = standalone)
- `tmux-claude-status`: add URL fetch + cache write before existing bridge-file read
- `QUOTA_DATA_PATH`: demote from user-facing to internal

### Pitfalls Flagged
- Don't use async (curl_cffi is sync)
- Don't use Alpine Docker (curl_cffi needs glibc)
- Don't add client retry logic (cache TTL handles it)
- Don't over-structure the package (~300 lines total)

## Open Questions for Design
- Stale data visual indicator — should tmux show dimmed colors when cache is 5-30 min old?
- Server scrape interval — reuse `QUOTA_REFRESH_PERIOD` semantics or independent config?
- Default host binding — `0.0.0.0` (all interfaces) vs `127.0.0.1` (localhost only)?
- API key auth mechanism — header name? (`X-API-Key`? `Authorization: Bearer`?)
