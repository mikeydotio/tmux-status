# Research: Client-Side Caching & Resilience Patterns

## Context
tmux-status renders every 5 seconds. The client needs quota data but should not hit the network on every render. Current approach: read a local JSON file. New approach: optionally fetch from a remote server with local file cache.

## Client-Side Caching Strategy

### Recommended: File-based cache with mtime TTL (Confidence: High)

This matches the existing pattern perfectly:
1. Client checks if local cache file exists and `mtime < 60 seconds ago`
2. If fresh → read from cache file, done
3. If stale or missing → HTTP GET from server → write to cache file (atomic rename)
4. If HTTP fails → use stale cache (with visual indicator)

**Why mtime-based, not HTTP cache headers:**
- The client is a bash/Python script running inside a tmux `#(...)` shell expansion
- Every invocation is a fresh process — no persistent HTTP client to track ETags
- Checking file mtime is a single `stat()` call — cheaper than any HTTP request
- The server's data only changes every ~60-300 seconds anyway

**Cache file location**: `~/.cache/tmux-status/claude-quota.json` — same path as standalone mode. The rendering script reads the same file regardless of mode. Only the writer changes (local poller vs. HTTP fetcher).

### HTTP Cache Headers (Server-Side)
The server should still set headers for any non-tmux clients:
- `Cache-Control: max-age=60, public` — matches the client TTL
- No need for ETag/Last-Modified — the data changes frequently and is small (<1KB)

## Health Check Design

### Recommended: Structured health with upstream status (Confidence: High)

```json
GET /health → 200
{
  "status": "ok",
  "uptime_seconds": 3600,
  "last_fetch": "2026-04-03T12:00:00Z",
  "last_fetch_status": "ok",
  "quota_age_seconds": 45
}
```

- `status`: "ok" | "degraded" (can't reach claude.ai but has cached data) | "error"
- Include `last_fetch` timestamp so operators can tell if scraping is working
- Keep it simple — no readiness/liveness split needed at this scale

## Error Handling & Degraded Mode

### Client behavior when server is unreachable (Confidence: High)

| Scenario | Client Behavior | tmux Display |
|----------|----------------|--------------|
| Server up, fresh data | Normal fetch + cache | Normal quota bars |
| Server up, server has stale upstream data | Server returns cached (still valid) | Normal quota bars |
| Server down, cache < 5 min old | Use stale cache | Normal quota bars (data still usable) |
| Server down, cache 5-30 min old | Use stale cache | Quota bars + dimmed/grey color to hint staleness |
| Server down, cache > 30 min old | Don't display quota | Quota section hidden (same as no-key behavior) |
| Server down, no cache at all | Don't display quota | Quota section hidden |

### Client timeout and retry (Confidence: High)
- HTTP timeout: **3 seconds** — generous for LAN/tailnet, fast enough to not block tmux rendering
- No retry within a single render cycle — if it fails, use cache, try again next time cache expires
- No circuit breaker needed — the 60s cache TTL naturally rate-limits retries

### Implementation in the rendering script
The existing Python block in `tmux-claude-status` already reads the quota bridge file. The change is minimal:
1. Read `QUOTA_SOURCE` from `settings.conf`
2. If set to a URL: check cache mtime → if stale, fetch from URL → write to cache
3. Then read cache file as before (unified code path)

This means the HTTP fetch logic goes in a small helper that runs before the existing bridge-file read, not a replacement for it.

## Similar Tools / Prior Art

### Prometheus pattern (Confidence: High)
- Server scrapes targets, stores metrics
- Clients (Grafana, alertmanager) query via HTTP
- Pull-based model — clients fetch when they need data
- Our server is the same: scrapes claude.ai, clients pull `/quota`

### waybar / polybar (Confidence: Medium)
- These status bars support custom scripts that can fetch from URLs
- Common pattern: script with local cache file, refresh on interval
- No standardized remote data protocol — each module is ad-hoc
- Our approach is cleaner (dedicated server with known API)

## Key Recommendations

1. **Unified cache path** — client writes fetched data to the same file the standalone poller writes to. Rendering script doesn't care about the source.
2. **3-second HTTP timeout** — fast fail on LAN, don't block tmux.
3. **Stale-while-revalidate** — always prefer stale data over no data, up to 30 minutes.
4. **No client-side complexity** — the "client" is just a small fetch-and-cache wrapper. All intelligence stays on the server.
