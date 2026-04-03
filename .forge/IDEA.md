# Quota Data Service: Standalone + Client/Server Architecture

## Vision
Decouple quota data scraping from quota data consumption so that tmux-status can operate either as a standalone installation (scrapes its own data) or as a client that fetches cached quota data from a lightweight REST API server on the local network or tailnet.

## Problem Statement
Currently, every tmux-status installation must independently scrape claude.ai for quota data, requiring each machine to have its own session key and run its own polling daemon. In multi-machine setups (e.g., agentsmith containers managed by a central host), this is redundant — a single host could scrape once and serve all clients. There's no way to share quota data across machines today.

## Target Users
- Solo developers running tmux-status on a single machine (standalone mode, current behavior)
- Developers with multiple machines/containers who want a centralized quota source (client/server mode)
- Infrastructure operators (e.g., coderig hosts) who want to provide quota data as a service to managed rigs

## Key Requirements
- [ ] Server component: standalone Python package that scrapes claude.ai and serves quota data via REST API
- [ ] Server holds the session key centrally — clients don't need their own
- [ ] `GET /quota` endpoint returns the same JSON structure as the current bridge file
- [ ] `GET /health` endpoint for monitoring
- [ ] Optional API key authentication (default: open, trust the network)
- [ ] API designed to be extensible for future data types (alerts, model availability, etc.)
- [ ] Client config: single `QUOTA_SOURCE` setting in settings.conf — URL means client mode, unset means standalone
- [ ] Client-side 1-minute local cache with TTL — most tmux render cycles (every 5s) read from cache, only fetch from server when stale
- [ ] Local cache path is an implementation detail, not user-configurable
- [ ] Standalone mode remains completely unchanged — local poller + local file
- [ ] Server installable independently (doesn't need full tmux-status)
- [ ] Server deployable via Docker, systemd, or manual execution
- [ ] Remove `QUOTA_DATA_PATH` as a user-facing config option (becomes internal)

## Assumptions (Examined)
| Assumption | Challenged? | Status |
|-----------|------------|--------|
| Tailnet/LAN is a sufficient auth boundary | Asked about auth model; user chose optional auth, default open | Validated |
| 1-minute cache TTL is appropriate | User explicitly requested; quota data changes slowly | Validated |
| Session key is the only credential needed | Current scraping already works this way | Validated |
| Python is acceptable for the server | Already a dependency for quota scripts; user confirmed separate package approach | Validated |
| Rendering script can handle HTTP fetch inline | It already runs Python inline; adding urllib/curl is minimal | Validated |

## Constraints
- Python 3 is the only guaranteed runtime (already a dependency)
- curl_cffi required for claude.ai scraping (server-side only, not needed on clients)
- Server must work without full tmux-status installed
- No new dependencies on clients — stdlib urllib is sufficient for HTTP fetch
- Must be backward compatible — existing standalone installations must not break

## What "Done" Looks Like
1. A `server/` directory with a self-contained quota server that can be installed and run independently
2. `tmux-claude-status` can fetch quota data from a remote server when `QUOTA_SOURCE` is set to a URL
3. Standalone mode (no `QUOTA_SOURCE`) works exactly as before
4. `QUOTA_DATA_PATH` removed from user-facing config; local cache path is internal
5. Server includes deployment examples (Dockerfile, systemd unit)

## Open Questions
- What port should the server default to? (e.g., 7850, 8080, configurable via CLI flag)
- Should the server support multiple session keys for multi-account scenarios?
- What's the server's scraping interval — reuse `QUOTA_REFRESH_PERIOD` semantics or its own config?
- Should the server log to stdout, a file, or both?
- Error handling: what does the client render when the server is unreachable and cache is stale?

## Prior Art
- Current `tmux-status-quota-fetch` + `tmux-status-quota-poll` — the scraping and caching logic that the server will absorb
- `QUOTA_DATA_PATH` (just added) — will be demoted from user config to internal detail
- `QUOTA_SOURCE` pattern — similar to how tools like Prometheus distinguish local vs. remote metric sources
