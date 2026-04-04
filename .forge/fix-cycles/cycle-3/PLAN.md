# Implementation Plan — Fix Cycle 2

## Summary

4 FIX items from triage pass 2. All are localized, low-risk changes. 2 are critical auth bypasses, 1 is a crash bug, 1 is auth integration test coverage.

## Task Breakdown

### Wave 1 (no dependencies — all parallel)

- [ ] T1.1: Fix auth bypass — abort(401) in check_auth hook
  - In `server/tmux_status_server/server.py` lines 74-84, replace `return json.dumps({"error": "invalid_or_missing_api_key"})` with `abort(401, json.dumps({"error": "invalid_or_missing_api_key"}))`. Remove the `response.status = 401` and `response.content_type = "application/json"` lines since abort() handles status. `abort` is already imported at line 68.
  - Acceptance: (1) `check_auth` calls `abort(401, ...)` instead of `return`. (2) All existing tests pass (update mocks if needed — the hook now raises HTTPError instead of returning a string).
  - Files: `server/tmux_status_server/server.py`

- [ ] T1.2: Fix empty API key file auth bypass
  - In `server/tmux_status_server/server.py` `_load_api_key()` (lines 55-64), after `f.read().strip()`, add: `if not key: logger.warning(...); return None`. Empty/whitespace-only key files should mean "no auth configured", not "auth with empty key".
  - Update existing tests in `test_server.py`: `test_empty_api_key_file_returns_empty_string` and `test_whitespace_only_api_key_file_returns_empty_string` — change assertions from `== ""` to `is None`.
  - Update `test_validate_gaps.py` `TestEmptyApiKeySecurityFinding` tests to reflect new behavior (empty key → auth disabled, not bypassable).
  - Acceptance: (1) `_load_api_key()` returns `None` for empty/whitespace-only key files. (2) `logger.warning` is called. (3) Updated tests pass.
  - Files: `server/tmux_status_server/server.py`, `server/tests/test_server.py`, `server/tests/test_validate_gaps.py`

- [ ] T1.3: Fix renderer None utilization guard
  - In `scripts/tmux-claude-status` line 189: change `"X" if fh_util == "X"` to `"X" if fh_util is None or fh_util == "X"`. Same at line 193 for `sd_util`.
  - Acceptance: (1) Lines 189 and 193 contain `is None or` guard before `round()`. (2) When utilization is `None`, renderer outputs "X%" instead of crashing.
  - Files: `scripts/tmux-claude-status`

### Wave 2 (depends on Wave 1)

- [ ] T2.1: Auth integration tests — WSGI-level proof of auth enforcement
  - Add new test class `TestAuthIntegrationWSGI` in `server/tests/test_server.py` using `webtest.TestApp` wrapping a real `QuotaServer._app`. Set `_api_key` and `_cached_data` directly on the server instance. No mocking of Bottle internals.
  - Required tests:
    1. Valid key → 200, body contains quota data
    2. Wrong key → 401, body does NOT contain quota data (check for absence of `utilization`, `org_uuid`)
    3. Missing key header → 401, body does NOT contain quota data
    4. /health → 200 regardless of auth state
    5. No auth configured (key=None) → /quota returns 200
    6. Empty X-API-Key header when key file was empty (FIX 1+4 combined) → auth disabled, 200
  - Depends on: T1.1, T1.2
  - Acceptance: (1) At least 5 WSGI integration tests exercise real Bottle request pipeline. (2) All existing 292+ tests pass. (3) Tests prove 401 responses contain zero quota data.
  - Files: `server/tests/test_server.py`

## Test Strategy

- **Unit tests**: Update existing mocked auth tests to expect `HTTPError` (abort) instead of return value from hook
- **Integration tests** (new): `webtest.TestApp` wrapping real Bottle WSGI app — the authoritative proof that auth blocks data leakage
- **Structural test**: Existing AST-based tests in `test_validate_gaps.py` verify source code patterns
- **Renderer tests**: Existing re-implementation tests in `test_validate_gaps.py` — update to cover None utilization

## Resumption Points

After Wave 1: all production code fixes are in. Server auth is fixed, renderer is fixed. Safe to pause.
After Wave 2: integration tests prove fixes work. Full cycle complete.

## Risk Register

1. **Bottle abort() in before_request hook** — abort() raises HTTPError which Bottle catches and converts to a response. Well-documented behavior. Low risk.
2. **webtest dependency** — Already installed (3.0.7) but not in pyproject.toml test deps. Tests will work but should note the dependency.
3. **Mock test breakage** — Existing TestAuthHook tests mock the hook return value. After abort(), the hook raises instead of returning. These tests need updating in T1.1 (not deferred to T2.1).
