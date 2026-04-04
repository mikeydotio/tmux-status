# Review Report

## Summary

Fix cycle 2 successfully resolved all four critical and important findings from the cycle 1 review. The auth bypass (TS-26) is fixed with `abort(401)`, the empty API key bypass (TS-27) is closed by returning `None`, the renderer None guard (TS-28) prevents `round(None)` crashes, and WSGI integration tests (TS-29) prove end-to-end auth enforcement. With 299 tests passing and zero failures, the server codebase is in solid shape. Two new findings emerged during this review, neither critical.

## Findings

### 1. API Key Not Re-read After Startup (Hot Rotation Not Supported)
- **Severity**: Useful
- **Description**: The API key is loaded once in `run()` (line 177) via `self._api_key = self._load_api_key()` and never refreshed. If an operator rotates the API key file on disk, the server continues using the old key until restarted. The session key, by contrast, is re-read on every scrape cycle (line 132). The design document does not explicitly require hot API key rotation, but the asymmetry is worth noting since it could surprise operators in production.
- **Location**: `server/tmux_status_server/server.py:177`
- **Option 1 (Recommended)**: Document that API key changes require a server restart (e.g., `systemctl --user restart tmux-status-server`). This is the simplest approach and consistent with how most services handle API key rotation.
- **Option 2**: Re-read the API key file periodically (e.g., on each request or on SIGUSR1). Adds complexity and file I/O to the hot path.

### 2. `__main__.py` Imports `parse_args` and `warn_if_exposed` But Never Uses Them
- **Severity**: Useful
- **Description**: `__main__.py` imports `parse_args` and `warn_if_exposed` from `config` (line 3) but delegates entirely to `_server_main()` which performs its own imports. The unused imports have no functional impact but add confusion. **Note**: This is the same issue as ESCALATED story TS-12 and is included here only to confirm it remains present after fix cycle 2 — it does NOT need to be re-triaged.
- **Location**: `server/tmux_status_server/__main__.py:3`

### 3. `read_session_key` Accepts `None` and Empty String as Valid `sessionKey` Values
- **Severity**: Useful
- **Description**: The `read_session_key` function checks only that the `sessionKey` key exists in the JSON dict (`"sessionKey" not in data`), not that its value is a non-empty string. A key file with `{"sessionKey": null}` or `{"sessionKey": ""}` passes validation and is sent to `fetch_quota`, which will construct a cookie header `sessionKey=None` or `sessionKey=` and make a failing HTTP request. The request will fail with a 401 from claude.ai, which the scraper correctly handles as `session_key_expired`. So there is no crash or data leak, but the error path is indirect and the error message misleading (the key is not "expired" — it is empty/null).
- **Location**: `server/tmux_status_server/scraper.py:77-80`
- **Option 1 (Recommended)**: Add a validation step: `if not data.get("sessionKey"): return {"error": "invalid_json"}`. This catches None, empty string, and other falsy values early with a clear error code.
- **Option 2**: Leave as-is. The upstream 401 handling works correctly; the error code is slightly misleading but functionally harmless.

## Design Alignment

**ALIGNED** — All fix cycle 2 changes match the design specification precisely:

- **Auth mechanism (DESIGN.md lines 194-199)**: The `before_request` hook now uses `abort(401, ...)` instead of returning a value, which correctly short-circuits request processing. The auth response format `{"error": "invalid_or_missing_api_key"}` matches the spec (line 174). `/health` remains exempt. `hmac.compare_digest()` is used for timing-safe comparison.

- **Error signaling (DESIGN.md lines 105-118)**: The renderer correctly handles `None` utilization by mapping it to `"X"`, consistent with the error signaling table. The `"X"` string displays as the error indicator in the tmux bar.

- **Empty key behavior**: `_load_api_key()` returns `None` for empty files, which the auth hook treats as "no key configured" (auth disabled). This is consistent with the design's "When no API key configured: all endpoints open, no headers checked" specification.

- **WSGI integration tests**: The `TestAuthIntegrationWSGI` class uses `webtest.TestApp` to exercise the full Bottle request pipeline, proving that auth 401 responses do not leak quota data, `/health` remains exempt, and valid keys grant access. This directly addresses the cycle 1 review finding that unit tests were verifying the wrong thing.

No drift from DESIGN.md was introduced in fix cycle 2.

## Story Hygiene

All four fix cycle 2 stories have been properly implemented and closed:

| Story | Title | Status | Verdict |
|-------|-------|--------|---------|
| TS-26 | Fix auth bypass — `abort(401)` in check_auth hook | done (archived) | pass |
| TS-27 | Fix empty API key file auth bypass — `_load_api_key()` returns None | done (archived) | pass |
| TS-28 | Fix renderer None utilization guard — add is-None-or check | done (archived) | pass |
| TS-29 | Add WSGI integration tests proving auth blocks data leakage | done (archived) | pass |

All four have passing verdicts in `verdicts.jsonl`. The 5 ESCALATE stories (TS-11, TS-12, TS-13, TS-22, TS-23) remain open in the backlog as expected.

Test suite: **299 passed, 0 failed** (verified during this review).

## Strengths

- **Auth fix is correct and complete**: The `abort(401)` call raises `bottle.HTTPError`, which Bottle catches before the route handler executes. The WSGI integration tests empirically prove no data leakage. This is the right fix for Bottle's hook semantics.

- **Defense in depth on empty key files**: The `_load_api_key()` method strips whitespace and returns `None` for empty/whitespace-only files. This prevents the `hmac.compare_digest("", "")` bypass vector entirely, because the auth hook short-circuits when `_api_key is None`.

- **Test quality improvement**: The addition of `TestAuthIntegrationWSGI` using `webtest.TestApp` closes the gap between unit-level mock tests and real HTTP behavior. The tests assert both the status code AND the absence of quota data in the response body — a thorough proof of non-leakage.

- **Renderer resilience**: The `is None or == "X"` guard in the renderer is the correct pattern. It handles both upstream API missing data (None) and server error signaling ("X") uniformly, preventing `TypeError` crashes without masking the error condition.

- **Atomic operations throughout**: Server uses GIL-safe reference swap for `_cached_data`. Client uses `tmp + os.replace()`. No partial reads are possible.

- **Error sanitization is consistent**: All error responses use machine-readable codes. No raw exception text appears in any API response, log message to clients, or cache file. The `_error_bridge` function enforces this invariant across all error paths.
