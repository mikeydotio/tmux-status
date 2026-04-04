# Handoff: Execute (Fix Cycle 2 Complete, Session 19)

## Context

Fix cycle 2 execution complete. All 4 stories done across sessions 16-19. Ready for review+validate pass.

## Stories Completed This Cycle

- **TS-26** (critical, wave 1, done): Fix auth bypass — `abort(401, ...)` in check_auth hook. Commit: `5ab8f34`.
- **TS-27** (critical, wave 1, done): Fix empty API key file — `_load_api_key()` returns None. Commit: `7583ef7`.
- **TS-28** (high, wave 1, done): Fix renderer None utilization guard — `is None or` guard. Commit: `c4e7727`.
- **TS-29** (high, wave 2, done): Auth WSGI integration tests — 6 webtest.TestApp tests proving auth blocks data leakage. Commit: `c533a8a`.

## Cold-Start Essentials

### Patterns Established

- Auth tests use `mb.abort.assert_called_once()` + `mb.abort.call_args[0]` to verify abort was called with `(401, json_body)`.
- WSGI integration tests use `webtest.TestApp(server._app)` wrapping real Bottle pipeline — no mocking of Bottle internals.
- `_load_api_key()` returns None in three cases: no api_key_file configured, file unreadable (OSError), file empty/whitespace. All three result in auth hook short-circuiting (no auth enforced).
- Renderer guards: `is None or` before string comparison ensures None values from JSON produce "X%" display instead of crashing.
- 401 data leakage proof: assertNotIn for utilization, org_uuid, org-abc-123, five_hour, seven_day in response body text.

### Micro-Decisions

- Bottle's `abort(401)` returns `text/html`, not `application/json` — WSGI integration 401 assertions use `resp.text` not `resp.json`.
- `_make_wsgi_server()` helper creates real QuotaServer with `_api_key` and `_cached_data` set directly, avoiding need to mock file I/O.
- `_SAMPLE_QUOTA_DATA` module-level constant shared across all WSGI integration tests for consistency.

### Code Landmarks

- `server/tmux_status_server/server.py:55-67` — `_load_api_key()` with empty-file guard
- `server/tmux_status_server/server.py:74-82` — check_auth hook with abort(401)
- `scripts/tmux-claude-status:189,193` — utilization None guards
- `server/tests/test_server.py:1344-1482` — TestAuthIntegrationWSGI (6 WSGI tests)
- `server/tests/test_server.py:1084-1109` — TestApiKeyEdgeCases

### Test State

- **299 tests passing**, 0 failures, 1 warning (webob/cgi deprecation — third-party)
- Run command: `python3 -m pytest server/tests/ -v`
- webtest installed via `python3-webtest` system package (apt)
- No special env setup needed

## Pipeline State

- Fix cycle: 2 / 3 (max)
- ESCALATE stories pending: 5 (TS-11, TS-12, TS-13, TS-22, TS-23)
- All fix cycle 2 stories complete — ready for review+validate
