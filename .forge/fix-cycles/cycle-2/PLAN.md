# Fix Cycle 2 -- Implementation Plan

## Requirements

| ID | Requirement | Type | Priority |
|----|-------------|------|----------|
| R1 | Auth bypass: `check_auth` hook must use `abort(401)` to stop request processing | functional | critical |
| R2 | Integration tests proving auth blocks data leakage through the full Bottle request pipeline | functional | critical |
| R3 | Renderer None guard: `round(None)` crash prevented when utilization is null | functional | important |
| R4 | Empty API key file treated as "no key" (returns None, logs WARNING, disables auth) | functional | critical |
| R5 | All existing 292 tests continue to pass after all fixes | non-functional | critical |
| R6 | Existing unit-level auth tests updated to reflect new abort()-based behavior | implicit | critical |

## Task Waves

### Wave 1 (parallel -- no dependencies)

#### T1.1: Fix auth bypass -- abort(401) instead of return
- **Requirement(s)**: R1
- **Description**: In `server/tmux_status_server/server.py`, replace the `return json.dumps(...)` on line 84 of the `check_auth` before_request hook with `abort(401, json.dumps({"error": "invalid_or_missing_api_key"}))`. Remove lines 82-83 (`response.status = 401` and `response.content_type = "application/json"`) since `abort()` handles the status code. `abort` is already imported at line 68.
- **Acceptance criteria**:
  - [ ] The `check_auth` hook calls `abort(401, ...)` instead of returning a JSON string
  - [ ] The lines `response.status = 401` and `response.content_type = "application/json"` are removed from the auth rejection branch
  - [ ] The `abort` import on line 68 is still present (already imported, no change needed)
  - [ ] The hook still returns `None` (no-op) for: (a) `self._api_key is None`, (b) `request.path == "/health"`, (c) valid API key
- **Expected files**: `server/tmux_status_server/server.py` (lines 74-84 modified)
- **Estimated scope**: small

#### T1.2: Fix empty API key file auth bypass
- **Requirement(s)**: R4
- **Description**: In `server/tmux_status_server/server.py`, in the `_load_api_key()` method (lines 55-64), after `key = f.read().strip()`, add a check: `if not key: logger.warning("API key file %s is empty, auth disabled", self.api_key_file); return None`. This prevents an empty key file from enabling auth with an empty-string key (which matches `hmac.compare_digest("", "")`).
- **Acceptance criteria**:
  - [ ] `_load_api_key()` returns `None` when the key file exists but is empty
  - [ ] `_load_api_key()` returns `None` when the key file contains only whitespace
  - [ ] A WARNING log message is emitted mentioning the file path and that auth is disabled
  - [ ] `_load_api_key()` still returns the stripped key string for non-empty key files
  - [ ] `_load_api_key()` still returns `None` for missing files (existing behavior preserved)
  - [ ] `_load_api_key()` still returns `None` when `api_key_file` is `None` (existing behavior preserved)
- **Expected files**: `server/tmux_status_server/server.py` (lines 55-64 modified)
- **Estimated scope**: small

#### T1.3: Fix renderer None guard for utilization
- **Requirement(s)**: R3
- **Description**: In `scripts/tmux-claude-status`, change the guards at lines 189 and 193 to also handle `None`:
  - Line 189: `five_hour_pct = "X" if fh_util is None or fh_util == "X" else round(fh_util)`
  - Line 193: `seven_day_pct = "X" if sd_util is None or sd_util == "X" else round(sd_util)`
- **Acceptance criteria**:
  - [ ] Line 189 reads: `five_hour_pct = "X" if fh_util is None or fh_util == "X" else round(fh_util)`
  - [ ] Line 193 reads: `seven_day_pct = "X" if sd_util is None or sd_util == "X" else round(sd_util)`
  - [ ] When `fh_util` is `None`, `five_hour_pct` is set to the string `"X"` (no crash)
  - [ ] When `sd_util` is `None`, `seven_day_pct` is set to the string `"X"` (no crash)
  - [ ] When `fh_util` is a number (e.g. `42.7`), `five_hour_pct` is set to `round(42.7)` = `43` (existing behavior preserved)
  - [ ] When `fh_util` is the string `"X"`, `five_hour_pct` is set to `"X"` (existing behavior preserved)
- **Expected files**: `scripts/tmux-claude-status` (lines 189, 193 modified)
- **Estimated scope**: small

### Wave 2 (depends on Wave 1)

#### T2.1: Update existing unit auth tests for abort() behavior
- **Requirement(s)**: R6, R5
- **Depends on**: T1.1
- **Description**: The existing `TestAuthHook` tests (lines 518-573 of `test_server.py`) call `hooks["before_request"]()` directly and assert on the return value. After T1.1, the hook will call `abort(401, ...)` which raises an exception in real Bottle. Since the test uses a mock Bottle, the `abort` mock must be configured to raise (or the tests updated to expect the mock abort to be called). Specifically:
  - `test_blocks_missing_header` and `test_blocks_wrong_key` currently assert `result is not None` and parse the return value as JSON. After the fix, the hook calls `abort()` instead of returning. The mock `abort` needs to be set up so these tests verify `abort` was called with status 401 and the error JSON body.
  - `test_empty_api_key_file_returns_empty_string` and `test_whitespace_only_api_key_file_returns_empty_string` in `TestApiKeyEdgeCases` must be updated: they currently assert `result == ""` but after T1.2 these should assert `result is None`.
- **Acceptance criteria**:
  - [ ] `test_blocks_missing_header` verifies that `abort` is called with status code 401 and a JSON body containing `{"error": "invalid_or_missing_api_key"}`
  - [ ] `test_blocks_wrong_key` verifies that `abort` is called with status code 401 and a JSON body containing `{"error": "invalid_or_missing_api_key"}`
  - [ ] `test_passes_correct_key` still verifies that the hook returns `None` (no abort called)
  - [ ] `test_no_auth_when_no_api_key` still verifies the hook returns `None`
  - [ ] `test_health_exempt_from_auth` still verifies the hook returns `None`
  - [ ] `test_empty_api_key_file_returns_empty_string` updated to assert `_load_api_key()` returns `None`
  - [ ] `test_whitespace_only_api_key_file_returns_empty_string` updated to assert `_load_api_key()` returns `None`
  - [ ] Running `python -m pytest server/tests/test_server.py` passes with 0 failures
- **Expected files**: `server/tests/test_server.py` (TestAuthHook class and TestApiKeyEdgeCases class modified)
- **Estimated scope**: medium

#### T2.2: Add integration tests for auth pipeline
- **Requirement(s)**: R2, R5
- **Depends on**: T1.1, T1.2
- **Description**: Add a new test class (e.g., `TestAuthIntegration`) in `server/tests/test_server.py` that exercises the full Bottle request pipeline. Use `webtest.TestApp` (if available) or Bottle's built-in `app.wsgi` interface to send real HTTP requests through the Bottle WSGI app. The tests must verify that:
  1. Valid API key on `/quota` returns 200 and the response body contains quota data.
  2. Wrong API key on `/quota` returns 401 and the response body does NOT contain quota data (no `five_hour`, `seven_day`, `utilization` keys).
  3. Missing API key header on `/quota` returns 401 and the response body does NOT contain quota data.
  4. `/health` returns 200 regardless of API key presence/absence.

  These tests instantiate a real `QuotaServer` (with real Bottle, not mocked) and use the WSGI callable directly without starting an HTTP listener. Seed `_cached_data` with known quota data so the test can verify the 401 body does not leak it.
- **Acceptance criteria**:
  - [ ] At least 4 integration tests exist in a dedicated test class
  - [ ] Test 1: GET `/quota` with valid `X-API-Key` header returns HTTP 200; response body is valid JSON containing `five_hour` and `seven_day` keys
  - [ ] Test 2: GET `/quota` with wrong `X-API-Key` header returns HTTP 401; response body does NOT contain `five_hour`, `seven_day`, or `utilization` keys
  - [ ] Test 3: GET `/quota` with no `X-API-Key` header returns HTTP 401; response body does NOT contain `five_hour`, `seven_day`, or `utilization` keys
  - [ ] Test 4: GET `/health` with no API key returns HTTP 200 even when auth is configured
  - [ ] Tests use the real Bottle WSGI app (not mocked) -- either via `webtest.TestApp` or direct WSGI `__call__`
  - [ ] Running `python -m pytest server/tests/` passes with 0 failures (all 292+ existing tests plus new ones)
- **Expected files**: `server/tests/test_server.py` (new test class added)
- **Estimated scope**: medium

## Requirement Traceability

| Requirement | Tasks | Coverage |
|-------------|-------|---------|
| R1: Auth bypass abort(401) | T1.1 | full |
| R2: Integration tests for auth pipeline | T2.2 | full |
| R3: Renderer None guard | T1.3 | full |
| R4: Empty API key file returns None | T1.2 | full |
| R5: All 292 existing tests pass | T2.1, T2.2 | full (T2.1 updates tests broken by fixes; T2.2 verifies full suite) |
| R6: Existing auth unit tests updated | T2.1 | full |

## Dependency Graph

```
T1.1 (abort fix) ──┐
                    ├──> T2.1 (update unit tests) ──┐
T1.2 (empty key) ──┘                                ├──> [done]
                    ┌──> T2.2 (integration tests) ──┘
T1.1 (abort fix) ──┤
T1.2 (empty key) ──┘

T1.3 (None guard) ──────────────────────────────────> [done]
```

- **T1.1, T1.2, T1.3**: All independent; can execute in parallel.
- **T2.1**: Depends on T1.1 (abort behavior changes what tests assert) and T1.2 (empty key behavior changes test expectations).
- **T2.2**: Depends on T1.1 and T1.2 (integration tests must verify the fixed behavior).
- **T2.1 and T2.2**: Independent of each other (different test classes, different test approaches). Can run in parallel once Wave 1 is complete.
- **T1.3**: Fully independent from all other tasks. No downstream dependents.

## Risks

| Risk | Impact | Mitigation |
|------|--------|-----------|
| `webtest` not installed as a dependency | T2.2 cannot use `TestApp` approach | Fall back to Bottle's built-in WSGI callable (`app(environ, start_response)`) or `bottle.TestApp` if available. Bottle can be called as a WSGI app without webtest. |
| Mock Bottle in existing tests does not support `abort()` raising | T2.1 tests may need mock reconfiguration | Configure mock `abort` to raise an exception (matching real Bottle behavior) so unit tests validate the correct flow |
| Changing `_load_api_key` return value breaks other tests | Unexpected test failures beyond the known 2 | Search all test files for `_load_api_key` references before modifying; the grep shows only `TestApiKeyLoading` and `TestApiKeyEdgeCases` are affected |
| `abort()` in Bottle sets `Content-Type: text/html` by default | Integration tests may need to check for JSON differently | The abort body is passed as plain text; verify the 401 body content via substring matching rather than JSON parsing of the top-level response |

## Scope Boundaries

### IN Scope
- Fix the `check_auth` hook to use `abort(401)` (T1.1)
- Fix `_load_api_key()` empty key handling (T1.2)
- Fix renderer None guard on utilization (T1.3)
- Update existing unit tests broken by the above fixes (T2.1)
- Add new integration tests for auth pipeline (T2.2)

### OUT of Scope
- SIGTERM shutdown fix (ESCALATE -- TS-22)
- Client `_maybe_fetch_quota` extraction (ESCALATE -- TS-23)
- pip stderr suppression (DEFER)
- `_error_bridge` private API naming (DEFER)
- API key file permission checking (DEFER)
- Any changes to the scraper, config, or install scripts
- Any changes to the quota-fetch pipeline or context hook

## Test Strategy

1. **Wave 1 verification**: After T1.1 and T1.2, run `python -m pytest server/tests/test_server.py -x` to identify which existing tests break (expected: `test_blocks_missing_header`, `test_blocks_wrong_key`, `test_empty_api_key_file_returns_empty_string`, `test_whitespace_only_api_key_file_returns_empty_string`). After T1.3, manually verify the guard text at lines 189/193.
2. **Wave 2 verification**: After T2.1, run `python -m pytest server/tests/test_server.py` -- all existing tests should pass. After T2.2, run `python -m pytest server/tests/` -- full suite (292+ tests) should pass with 0 failures.
3. **Final gate**: `python -m pytest server/tests/` must exit 0 with all tests passing (original 292 minus any intentionally removed + new integration tests).

## Resumption State

| Task | Status | Notes |
|------|--------|-------|
| T1.1 | not started | |
| T1.2 | not started | |
| T1.3 | not started | |
| T2.1 | not started | blocked on T1.1, T1.2 |
| T2.2 | not started | blocked on T1.1, T1.2 |

## Deviation Log

| Task | Planned | Actual | Impact | Decision |
|------|---------|--------|--------|----------|
| (none yet) | | | | |
