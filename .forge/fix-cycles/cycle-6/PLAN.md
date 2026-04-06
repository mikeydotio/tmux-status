# Implementation Plan — ESCALATE Fix Cycle 6

## Context

Two ESCALATE stories promoted from fix cycle 5 (max fix cycles exceeded). User has approved approaches for both.

## Task Breakdown

### Wave 1 (no dependencies)

- [ ] T1.1: Fix $TRANSCRIPT shell interpolation via env var (TS-39)
  - In `scripts/tmux-claude-status`, change line 46 from `eval "$(python3 << PYEOF` to `eval "$(TRANSCRIPT="$TRANSCRIPT" python3 << PYEOF`
  - Change line 49 from `transcript = "$TRANSCRIPT"` to `transcript = os.environ["TRANSCRIPT"]`
  - Acceptance: `$TRANSCRIPT` no longer appears as a bare shell variable inside the Python heredoc; Python reads the value via `os.environ["TRANSCRIPT"]`; existing transcript parsing logic is unchanged (model, effort, context detection all still work); `bash -n scripts/tmux-claude-status` exits 0
  - Files: `scripts/tmux-claude-status`

- [ ] T1.2: Add @app.error(401) JSON handler (TS-40)
  - In `server/tmux_status_server/server.py`, add `@app.error(401)` handler after the existing `@app.error(500)` block, matching the same pattern: set `response.content_type = "application/json"`, return `json.dumps({"error": "unauthorized"})`
  - Acceptance: `@app.error(401)` handler exists in server.py; 401 responses have `Content-Type: application/json`; response body is valid JSON with `{"error": "unauthorized"}`; existing auth tests still pass
  - Files: `server/tmux_status_server/server.py`

### Wave 2 (depends on Wave 1)

- [ ] T2.1: Update 401 content-type test assertion
  - In `server/tests/test_server.py`, update `test_401_response_content_type_is_json` to assert `resp.content_type` contains `application/json` and `json.loads(resp.text)` returns a dict with `"error"` key
  - Acceptance: Test asserts content_type is application/json; test asserts body is valid JSON; all existing tests pass
  - Files: `server/tests/test_server.py`

## Test Strategy

- Wave 1 T1.1: Manual verification — the renderer script has no automated test harness. Verify the env var pattern works by checking `os.environ["TRANSCRIPT"]` is syntactically correct Python in the heredoc context. `bash -n` syntax check.
- Wave 1 T1.2: Run existing test suite — existing auth WSGI tests already check 401 status codes. The new error handler should make `test_401_response_content_type_is_json` pass more cleanly.
- Wave 2 T2.1: Strengthen the existing test to assert JSON content-type, then run full suite.

## Resumption Points

- After Wave 1: Both fixes are independent and complete. Tests can be run.
- After Wave 2: Test hardened. Ready for review.

## Risk Register

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Renderer regression (T1.1) | Medium — status bar breaks | Change is minimal (2 lines), env var pattern is well-established |
| Bottle error handler precedence (T1.2) | Low — abort body ignored | Custom handler returns its own JSON, which is the desired behavior |
