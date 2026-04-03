# Handoff: QA Engineer — Test Strategy

## Timestamp
2026-04-03T15:00:00Z

## Test Strategy Overview

This project has zero existing tests. The new server component handles credentials, serves a network API, and has security-sensitive auth. The test strategy focuses on what would catch real production bugs: auth bypass, credential leaks in responses, data corruption in the bridge format, and silent failures that break the tmux status bar.

**Framework:** `pytest` (with no plugins beyond what ships with it). Minimal infrastructure. One `conftest.py` with shared fixtures. No coverage enforcement -- coverage tools are noise on a 300-line server; manual review of edge cases is more valuable.

**Guiding principle:** Test the server as a real HTTP server. Bottle is lightweight enough to spin up in-process for each test. The only thing we mock is `curl_cffi` network calls to claude.ai -- everything else runs real code against real (temporary) files and a real HTTP stack.

## What to Test vs. What to Skip

### Test (high bug-risk, production impact)

| Component | Why It Matters | Test Type |
|-----------|---------------|-----------|
| **Auth middleware** | Security bypass = anyone reads your quota data | Integration (real HTTP requests to real Bottle server) |
| **Error sanitization** | Raw exception in response = information disclosure | Integration |
| **`/quota` response format** | Wrong shape = renderer crashes silently, shows nothing | Integration + contract |
| **`/health` response format** | Wrong shape = monitoring broken | Integration + contract |
| **Config parsing (`config.py`)** | Bad defaults = server binds to wrong address or refuses to start | Unit |
| **Key file permission check** | Wrong check = either refuses valid key or accepts world-readable key | Unit (real temp files with real chmod) |
| **Session key parsing** | Fails to read valid key = server shows "no_key" permanently | Unit (real temp files) |
| **Error status mapping** | Wrong status code mapping = misleading error in status bar | Unit |
| **Scraper data extraction** | Wrong field names = null utilization forever | Unit (with fake HTTP response data) |
| **Client `_maybe_fetch_quota` function** | Fetch failure = no quota display; cache corruption = crash | Integration (real HTTP to test server, real temp files) |
| **Startup warning for 0.0.0.0 without auth** | Missing warning = silent security misconfiguration | Unit |

### Skip (diminishing returns)

| Component | Why Skip |
|-----------|----------|
| Bottle framework routing | Well-tested upstream; our routes are trivial |
| `curl_cffi` TLS impersonation | Cannot test without hitting claude.ai; that is an acceptance test |
| tmux rendering output (bash script) | Shell string formatting; visual verification only |
| install.sh / uninstall.sh | Platform-specific, interactive; manual QA only |
| systemd/launchd daemon lifecycle | OS integration; manual QA only |
| Thread scheduling/timing | GIL-protected reference swap; no lock needed per design |

## Architecture: What Gets Mocked vs. Real

### Real (no mocks)

- **HTTP server:** Each test starts a real Bottle app via `webtest.TestApp` or `bottle.default_app()` with WSGI. No HTTP mocking. Tests hit real route handlers through real WSGI calls.
- **File I/O:** All credential files, config files, and cache files use real `tempfile.TemporaryDirectory` paths with real `os.chmod`. This catches permission bugs, path expansion bugs, and atomic write bugs.
- **JSON serialization:** All response bodies are parsed as real JSON and validated against the contract schema.
- **Auth middleware:** Real `hmac.compare_digest` with real headers on real WSGI requests.

### Mocked (external service only)

- **`curl_cffi.requests.get`:** The only mock in the entire suite. This is the network call to claude.ai. We replace it with a function that returns canned response objects (status code + JSON body). This is the textbook acceptable mock: an external service we cannot control in tests.

### Rationale

The Bottle server is fast enough to start per-test (no network socket needed -- WSGI test client). Temp files are fast. There is zero reason to mock file I/O or the HTTP framework when the real things work in milliseconds.

## Test File Layout

```
server/
  tests/
    conftest.py          # Shared fixtures: temp dirs, test app, mock scraper
    test_config.py       # CLI arg parsing, defaults, validation
    test_auth.py         # API key auth middleware (security-critical)
    test_quota_endpoint.py   # GET /quota contract + error conditions
    test_health_endpoint.py  # GET /health contract
    test_scraper.py      # Scraper logic with mocked curl_cffi
    test_key_file.py     # Session key reading, permission checks
    test_client_fetch.py # Client-side _maybe_fetch_quota function
```

Total: ~7 test files, estimated 40-60 test cases.

## Critical Test Cases

### 1. Auth Middleware (`test_auth.py`) -- SECURITY CRITICAL

These are the most important tests in the suite. An auth bypass means anyone on the network reads your Claude quota (and confirms your session key is valid).

```
test_missing_api_key_header_returns_401
  - Server configured with API key
  - Request to /quota with no X-API-Key header
  - Assert: 401, body is {"error": "invalid_or_missing_api_key"}
  - Assert: response contains NO quota data fields

test_wrong_api_key_returns_401
  - Server configured with API key "correct-key-abc123"
  - Request with X-API-Key: "wrong-key-xyz789"
  - Assert: 401

test_correct_api_key_returns_200
  - Server configured with API key "correct-key-abc123"
  - Request with X-API-Key: "correct-key-abc123"
  - Assert: 200, body contains quota data

test_health_endpoint_bypasses_auth
  - Server configured with API key
  - Request to /health with NO X-API-Key header
  - Assert: 200 (not 401)

test_no_api_key_configured_allows_all_requests
  - Server started without --api-key-file
  - Request to /quota with no header
  - Assert: 200 (auth disabled)

test_timing_safe_comparison_used
  - Verify hmac.compare_digest is called (not == operator)
  - This is a code inspection test -- assert the auth function uses hmac.compare_digest
  - Alternatively: verify auth takes similar time for near-miss vs. totally wrong keys
    (though timing tests are inherently flaky; code inspection is more reliable)

test_empty_api_key_header_returns_401
  - X-API-Key: "" (empty string)
  - Assert: 401

test_api_key_with_whitespace_trimming
  - API key file contains "mykey\n" (trailing newline, common in files)
  - Request with X-API-Key: "mykey"
  - Assert: 200 (key file should be stripped)

test_api_key_with_leading_trailing_spaces
  - API key file contains "  mykey  \n"
  - Request with X-API-Key: "mykey"
  - Assert: 200 (strip whitespace from file)
```

### 2. Error Sanitization -- SECURITY SENSITIVE

```
test_scraper_exception_not_leaked_in_quota_response
  - Scraper raises ValueError("secret internal path /home/user/.config/...")
  - GET /quota
  - Assert: response body does NOT contain "/home/user" or the exception message
  - Assert: response contains generic error code like "upstream_error"

test_unknown_route_returns_generic_404
  - GET /nonexistent
  - Assert: 404, body does not contain stack trace or file paths

test_internal_error_returns_generic_500
  - Force a route handler exception
  - Assert: 500, body is {"error": "internal_error"} (no traceback)
```

### 3. `/quota` Response Contract (`test_quota_endpoint.py`)

```
test_quota_ok_response_has_required_fields
  - Scraper has valid data
  - Assert response has: status, org_uuid, five_hour.utilization, five_hour.resets_at,
    seven_day.utilization, seven_day.resets_at, timestamp
  - Assert: utilization values are integers (not strings) when status is "ok"
  - Assert: timestamp is a recent Unix epoch integer

test_quota_error_response_has_X_utilization
  - Scraper has error status (e.g., "expired")
  - Assert: five_hour.utilization == "X" (string, not integer)
  - Assert: seven_day.utilization == "X"
  - Assert: status field reflects the error type

test_quota_starting_response_returns_503
  - Server just started, no scrape completed yet
  - Assert: HTTP 503
  - Assert: status == "starting"
  - Assert: utilization values are "X"

test_quota_response_content_type_is_json
  - Assert: Content-Type header is application/json

test_quota_error_statuses_all_have_error_field
  - For each error status: expired, blocked, rate_limited, no_key, upstream_error
  - Assert: response includes "error" field with machine-readable code

test_quota_ok_utilization_is_integer_0_to_100
  - Scraper returns utilization: 42
  - Assert: type(response["five_hour"]["utilization"]) is int
  - Assert: 0 <= value <= 100

test_quota_utilization_boundary_values
  - Test utilization: 0 (fresh reset), 100 (fully consumed), 50 (midpoint)
  - Assert: all render correctly as integers
```

### 4. `/health` Endpoint (`test_health_endpoint.py`)

```
test_health_returns_required_fields
  - Assert: status, uptime_seconds, version present
  - Assert: uptime_seconds >= 0
  - Assert: version matches expected format

test_health_status_reflects_scraper_state
  - Scraper succeeded last run -> status: "ok"
  - Scraper failed last run but has cached data -> status: "degraded"
  - No data at all -> status: "error"

test_health_uptime_increases
  - Call /health, note uptime
  - Wait briefly, call again
  - Assert: second uptime > first uptime (or equal, within 1s tolerance)
```

### 5. Config Parsing (`test_config.py`)

```
test_default_host_is_localhost
  - Parse with no --host flag
  - Assert: host == "127.0.0.1"

test_default_port_is_7850
  - Parse with no --port flag
  - Assert: port == 7850

test_custom_port_accepted
  - Parse with --port 9999
  - Assert: port == 9999

test_invalid_port_rejected
  - Parse with --port 99999 (out of range)
  - Assert: error raised

test_api_key_file_not_found_raises_error
  - Parse with --api-key-file /nonexistent/path
  - Assert: error raised at startup (not silently ignored)

test_warn_on_0000_without_api_key
  - Parse with --host 0.0.0.0, no --api-key-file
  - Assert: warning logged (capture log output)

test_no_warn_on_0000_with_api_key
  - Parse with --host 0.0.0.0 --api-key-file valid_file
  - Assert: no warning logged
```

### 6. Key File Handling (`test_key_file.py`) -- SECURITY SENSITIVE

```
test_read_valid_json_key_file
  - Create temp file: {"sessionKey": "sk-ant-abc123", "expiresAt": "2026-12-31T00:00:00Z"}
  - chmod 600
  - Assert: returns correct sessionKey and expiresAt

test_read_bare_string_key_file
  - File contains just "sk-ant-abc123" (no JSON wrapper)
  - Assert: returns {"sessionKey": "sk-ant-abc123"}

test_reject_world_readable_key_file
  - Create temp file, chmod 644 (world-readable)
  - Assert: server refuses to start / raises error with clear message

test_reject_group_readable_key_file
  - chmod 640
  - Assert: rejected

test_accept_600_permissions
  - chmod 600
  - Assert: accepted

test_accept_400_permissions
  - chmod 400 (read-only by owner)
  - Assert: accepted

test_missing_key_file_returns_no_key_status
  - No key file exists, no env var
  - Assert: scraper returns status: "no_key"

test_expired_key_detected
  - Key file with expiresAt in the past
  - Assert: status: "expired" (not attempted network call)

test_key_file_with_unicode_content
  - File contains non-ASCII bytes
  - Assert: handled gracefully (error, not crash)

test_empty_key_file
  - File exists but is empty (0 bytes)
  - Assert: returns no_key status (not crash)

test_malformed_json_key_file
  - File contains "{ broken json"
  - Assert: handled gracefully, falls through to bare string parsing or error
```

### 7. Scraper Logic (`test_scraper.py`) -- curl_cffi MOCKED

This is the ONE place we mock: `curl_cffi.requests.get` is replaced with a function returning canned responses. The scraper logic itself (org discovery, field extraction, error mapping) runs real code.

```
test_successful_org_discovery_and_usage_fetch
  - Mock returns: org list [{"uuid": "org-123"}], then usage data
  - Assert: scraper produces bridge dict with status:"ok", correct org_uuid, utilization values

test_org_uuid_cached_after_first_discovery
  - First call: mock returns org list
  - Second call: mock should NOT be called for /organizations (only /usage)
  - Assert: org_uuid reused from cache

test_http_401_maps_to_expired_status
  - Mock returns status 401
  - Assert: scraper produces status: "expired", utilization: "X"

test_http_403_maps_to_blocked_status
  - Mock returns 403
  - Assert: status: "blocked"

test_http_429_maps_to_rate_limited_status
  - Mock returns 429
  - Assert: status: "rate_limited"

test_unexpected_http_status_maps_to_upstream_error
  - Mock returns 502
  - Assert: status: "upstream_error"

test_connection_timeout_maps_to_upstream_error
  - Mock raises ConnectionError or Timeout
  - Assert: status: "upstream_error", utilization: "X"

test_malformed_json_from_upstream
  - Mock returns 200 with body "not json"
  - Assert: graceful error, not crash

test_empty_org_list
  - Mock returns 200 with body []
  - Assert: error status (not crash, not index-out-of-bounds)

test_missing_utilization_field_in_usage_response
  - Mock returns 200 with usage data missing "five_hour" key
  - Assert: graceful handling (null/default, not KeyError crash)

test_org_response_missing_uuid_field
  - Mock returns [{"name": "My Org"}] (no uuid)
  - Assert: error status (not KeyError crash)
```

### 8. Client Fetch Function (`test_client_fetch.py`)

This tests the ~25-line `_maybe_fetch_quota` function that will be added to `tmux-claude-status`. We spin up a real Bottle test server and make real HTTP calls to it.

```
test_fetch_writes_valid_json_to_cache_file
  - Start test server returning valid quota JSON
  - Call _maybe_fetch_quota with cache_ttl=0
  - Assert: cache file exists, contains valid JSON matching server response

test_fetch_failure_leaves_stale_cache_intact
  - Write an existing cache file with known content
  - Point _maybe_fetch_quota at unreachable URL
  - Assert: cache file still has original content (not corrupted/deleted)

test_cache_ttl_skips_fetch_when_fresh
  - Write cache file with mtime = now
  - Set cache_ttl = 60
  - Call _maybe_fetch_quota
  - Assert: no HTTP request made (server not contacted)

test_cache_ttl_zero_always_fetches
  - Set cache_ttl = 0
  - Call _maybe_fetch_quota twice
  - Assert: server contacted both times

test_api_key_sent_in_header
  - Start test server that checks X-API-Key header
  - Call _maybe_fetch_quota with api_key="test-key"
  - Assert: server received the correct header

test_empty_source_url_is_noop
  - Call _maybe_fetch_quota with source_url=""
  - Assert: no HTTP request, no file written, no error

test_atomic_write_no_partial_cache
  - Verify the function writes to .tmp then renames
  - (Implementation detail, but atomic writes are a stated convention)

test_server_returns_invalid_json
  - Server returns "not json {{"
  - Assert: cache file NOT written (bad data rejected)
  - Assert: no exception raised (silent failure)

test_server_timeout
  - Server configured to delay response beyond 3s timeout
  - Assert: function returns without hanging, stale cache preserved
```

## Edge Case Coverage by Category

| Category | Applicable To | Key Tests | Notes |
|----------|--------------|-----------|-------|
| Empty/null | Key file, config args, API key header, response fields | Empty key file, empty API key header, missing response fields, no source URL | High priority -- these are common in real usage |
| Boundary values | Utilization 0/100, port 1/65535, cache TTL 0 | Utilization boundaries, port validation, TTL=0 behavior | TTL=0 is the default config, must work |
| Malformed input | Key file JSON, upstream API responses, config values | Broken JSON key file, non-JSON upstream, truncated responses | curl_cffi returns weird stuff when Cloudflare blocks |
| Permission errors | Key file chmod, API key auth | 644/640/600/400 permissions, wrong/missing/empty API keys | Security-critical category |
| Network failures | Client fetch, scraper upstream | Connection timeout, unreachable server, server error responses | Must degrade gracefully |
| Unicode and encoding | Key file content, upstream response | Unicode in key file, non-ASCII upstream data | Low priority but cheap to test |
| State transitions | Server startup (no data yet), scraper error->recovery | Starting state returns 503, health status degrades and recovers | "starting" state is user-visible |
| Concurrent operations | Not applicable at this scale | None | GIL-protected reference swap; not worth testing |
| Resource exhaustion | Not applicable | None | Personal tool, <10 clients |
| Large inputs | Not applicable | None | Responses are <1KB JSON |
| Temporal | Key expiry checking | Expired key detected, not-yet-expired key accepted | Must handle timezone-aware ISO8601 |

## Mock Audit

| What | Mocked? | Verdict | Rationale |
|------|---------|---------|-----------|
| `curl_cffi.requests.get` | YES | Acceptable | External service (claude.ai). Cannot hit in CI. Would require real session key. |
| Bottle HTTP server | NO | Correct | Use `webtest.TestApp` WSGI client -- runs real handlers, no network socket needed |
| File system (temp files) | NO | Correct | Use real `tempfile.TemporaryDirectory`. Tests real chmod, real atomic writes. |
| `hmac.compare_digest` | NO | Correct | Test the real function. Code inspection verifies it is used. |
| `json` module | NO | Correct | Test real serialization. |
| `time.time()` | Maybe | Acceptable if needed | Only for cache TTL freshness tests; prefer real short sleeps or file mtime manipulation |

## .env Requirements

None. This test suite requires zero environment variables or external credentials. All tests use:
- Temporary directories for file fixtures
- In-process WSGI test client (no network ports)
- Canned response data for the curl_cffi mock

No `.env.test.example` needed. A developer can run the full suite with just:
```bash
cd server/
pip install -e ".[test]"
pytest
```

## Dependencies to Add

In `server/pyproject.toml` under `[project.optional-dependencies]`:
```toml
[project.optional-dependencies]
test = [
    "pytest>=7.0",
    "webtest>=3.0",
]
```

`webtest` provides a WSGI test client for Bottle apps. It sends real WSGI requests through the app without needing a socket. This is the standard way to test Bottle/Pyramid/WSGI apps -- no mocking the HTTP layer.

## Test Execution

```bash
# Install server package with test deps
cd /home/mikey/tmux-status/server
pip install -e ".[test]"

# Run all tests
pytest tests/ -v

# Run just security tests
pytest tests/test_auth.py tests/test_key_file.py -v

# Run with short output
pytest tests/ -q
```

## What This Strategy Does NOT Cover (and why)

1. **Actual claude.ai scraping** -- Requires real session key, hits rate limits, subject to API changes. This is a manual acceptance test: run the server, check the output.

2. **tmux rendering correctness** -- The bash script that formats tmux color strings. Visual verification only. You look at your status bar and see if it looks right.

3. **install.sh / uninstall.sh** -- Platform-specific, interactive. Test manually on a clean VM/container.

4. **systemd/launchd integration** -- OS service lifecycle. Test by installing and checking `systemctl status` or `launchctl list`.

5. **Multi-client concurrent access** -- Bottle handles concurrent requests fine for <10 clients. Not worth simulating.

6. **Performance/load** -- This server handles one request every 5 seconds per tmux pane. Performance testing is meaningless.

## Recommendations for the Implementing Engineer

1. **Start with `test_auth.py`** -- security tests first. If auth is broken, nothing else matters.

2. **Use `webtest.TestApp`** for all HTTP tests. Example pattern:
   ```python
   from webtest import TestApp
   app = TestApp(bottle_app)
   resp = app.get('/quota', headers={'X-API-Key': 'test'})
   assert resp.json['status'] == 'ok'
   ```

3. **Use `tmp_path` pytest fixture** for all file operations. Never write to real config dirs.

4. **For the curl_cffi mock**, create a simple fixture:
   ```python
   @pytest.fixture
   def mock_cffi(monkeypatch):
       def make_response(status_code, json_body):
           # Return an object with .status_code and .json() 
           ...
       monkeypatch.setattr("server.scraper.cffi_requests.get", mock_fn)
   ```

5. **Keep test data realistic** -- use real-looking UUIDs (`"a1b2c3d4-e5f6-7890-abcd-ef1234567890"`), real-looking session keys (`"sk-ant-sid01-abc123..."`), real ISO timestamps.

6. **Run the suite in CI** if/when CI is set up. The entire suite should complete in <5 seconds (no network calls, no sleeps, no heavy setup).

## Pipeline State
- Fix cycle: 0 / 3
- Yolo mode: false
- Stories pending: 0
