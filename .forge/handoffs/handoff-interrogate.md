# Handoff: Interrogate → Research

## Step Completed
interrogate

## Key Decisions
- **Two-mode architecture**: standalone (local poller, current behavior) vs. client (fetches from REST server)
- **Single config key**: `QUOTA_SOURCE` — URL = client mode, unset = standalone
- **Server holds session key**: clients don't need their own
- **Optional auth**: default open (trust the network), optional API key
- **1-minute client cache**: rendering script checks mtime, only fetches from server when cache >60s old
- **Extensible API**: start with `/quota` and `/health`, designed for future endpoints
- **QUOTA_DATA_PATH demoted**: becomes internal implementation detail, removed from user-facing config

## Context for Next Step
### Requirements (priority order)
1. Server as standalone Python package in `server/` directory
2. `GET /quota` returning current bridge JSON format
3. `GET /health` for monitoring
4. Client-side rendering changes in `tmux-claude-status` (URL detection, HTTP fetch, cache TTL)
5. Optional API key auth on server
6. Deployment artifacts (Dockerfile, systemd unit)
7. Remove `QUOTA_DATA_PATH` from user-facing config

### Existing Code to Reuse
- `scripts/tmux-status-quota-fetch` — scraping logic, session key parsing, claude.ai API calls
- `scripts/tmux-status-quota-poll` — polling loop, signal handling, interval management
- Bridge JSON format — server response should match existing `claude-quota.json` structure

### User Preferences
- "You decide" on specific architecture choices — user trusts implementation judgment
- Separate package but not over-engineered — "a lil server"
- Must work on tailnet or any LAN

## Open Questions for Research
- Best minimal Python HTTP server approach (stdlib http.server vs. lightweight framework)
- Optimal server configuration model (CLI flags, env vars, config file)
- How to structure `server/` for independent installation (setup.py/pyproject.toml?)
- Error UX: what does tmux-status show when server is down and cache is stale?
