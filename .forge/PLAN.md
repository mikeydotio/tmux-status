# Implementation Plan -- Fix Cycle 6

## Requirements

| ID | Requirement | Type | Priority | Source |
|----|-------------|------|----------|--------|
| R1 | `$TRANSCRIPT` must not be shell-interpolated into the Python heredoc in `scripts/tmux-claude-status` | functional (security) | high | TS-39 |
| R2 | The server must return `Content-Type: application/json` for 401 responses, not HTML | functional (API contract) | high | TS-40 |
| R3 | Existing tests must continue to pass after both changes | non-functional (regression) | high | implicit |
| R4 | New tests must cover the specific fixes to prevent regression | non-functional (testing) | high | implicit |

## Task Waves

### Wave 1 (parallel -- no dependencies between T1.1 and T1.2)

#### T1.1: Fix $TRANSCRIPT shell interpolation in Python heredoc (TS-39)

- **Requirement(s)**: R1, R3
- **Acceptance criteria**:
  - [ ] Line 46 of `scripts/tmux-claude-status` passes TRANSCRIPT as an environment variable to python3: the line reads `eval "$(TRANSCRIPT="$TRANSCRIPT" python3 << PYEOF`
  - [ ] Line 49 of `scripts/tmux-claude-status` reads from `os.environ` instead of shell interpolation: the line reads `transcript = os.environ["TRANSCRIPT"]`
  - [ ] The string `"$TRANSCRIPT"` (with dollar sign inside quotes) does NOT appear anywhere in the Python heredoc block (lines 47-254)
  - [ ] `os` is imported within the heredoc (already present on line 47 -- verify it remains)
  - [ ] Running `bash -n scripts/tmux-claude-status` exits 0 (no syntax errors)
  - [ ] Running `python3 -c "import ast; ast.parse(open('/dev/stdin').read())"` against the extracted Python block between PYEOF markers parses without SyntaxError
- **Expected files**: `scripts/tmux-claude-status` (modify lines 46 and 49 only)
- **Estimated scope**: small (2-line change)

#### T1.2: Add @app.error(401) handler to server (TS-40)

- **Requirement(s)**: R2, R3, R4
- **Acceptance criteria**:
  - [ ] `server/tmux_status_server/server.py` contains an `@app.error(401)` handler function
  - [ ] The 401 error handler sets `response.content_type` to `"application/json"`
  - [ ] The 401 error handler returns `json.dumps({"error": "invalid_or_missing_api_key"})`
  - [ ] The handler is placed before the existing `@app.error(404)` handler (between line 118 and the 404 block)
  - [ ] In `server/tests/test_server.py`, the `test_error_handlers_registered` test asserts `401 in errors` (currently only checks 404 and 500)
  - [ ] A new unit test exists that calls `errors[401](mock_err)` and asserts the returned JSON contains `{"error": "invalid_or_missing_api_key"}`
  - [ ] The existing WSGI integration test `test_401_response_content_type_is_json` is updated to assert `resp.content_type` starts with `"application/json"` (currently it only checks body text contains the error string)
  - [ ] Running `python3 -m pytest server/tests/test_server.py` passes with 0 failures
- **Expected files**: `server/tmux_status_server/server.py` (add 4 lines), `server/tests/test_server.py` (modify/add ~10 lines)
- **Estimated scope**: small

### Wave 2 (depends on Wave 1)

#### T2.1: Full regression test run

- **Requirement(s)**: R3
- **Depends on**: T1.1, T1.2
- **Acceptance criteria**:
  - [ ] `python3 -m pytest server/tests/` passes with 0 failures
  - [ ] `bash -n scripts/tmux-claude-status` exits 0
  - [ ] `bash -n scripts/tmux-git-status` exits 0 (unchanged but verify no collateral)
- **Expected files**: none (verification only)
- **Estimated scope**: small

## Requirement Traceability

| Requirement | Tasks | Coverage |
|-------------|-------|----------|
| R1: No $TRANSCRIPT shell interpolation | T1.1 | full |
| R2: 401 returns JSON not HTML | T1.2 | full |
| R3: No regressions | T1.1, T1.2, T2.1 | full |
| R4: New test coverage for fixes | T1.2 | full |

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| T1.1: Env var not visible inside heredoc on all bash versions | Renderer outputs nothing; Claude status line goes blank | The `VAR=val command` syntax is POSIX sh -- universally supported. Verify with `bash -n`. |
| T1.1: `os.environ["TRANSCRIPT"]` raises KeyError if env var missing | Renderer crashes silently (exit 0 per convention) | This would only happen if the bash lines above fail to find a transcript, in which case the script already exits on line 43. The env var is always set when the heredoc executes. |
| T1.2: Bottle error handler signature mismatch | 401 returns 500 instead | The handler signature `def error401(err)` matches existing 404/500 handlers exactly. |
| T1.2: webtest may not exercise Bottle error handlers in same pipeline | Test passes but production still returns HTML | The existing WSGI tests for auth already return 401 via `abort()` -- extending them to check content_type exercises the real Bottle pipeline. |

## Scope Boundaries

**IN scope:**
- Fixing the 2 specific ESCALATE items (TS-39, TS-40) as described
- Updating existing tests to cover the fixes
- Adding minimal new tests for the 401 handler

**OUT of scope:**
- Quoting the entire heredoc (`<< 'PYEOF'`) -- this would require auditing all variable references and is a larger change (noted in TS-39 Option 1 but user chose Option 2)
- Refactoring the check_auth hook to avoid `abort()` (TS-40 Option 2 -- rejected)
- Adding error handlers for other HTTP status codes (e.g., 405, 403)
- Any changes to other scripts, the quota fetcher, or the context hook

## Deviation Log

| Task | Planned | Actual | Impact | Decision |
|------|---------|--------|--------|----------|
| (none yet) | | | | |

## Resumption State

- **Status**: Plan created, no tasks started
- **Next**: T1.1 and T1.2 can begin in parallel immediately
- **Blockers**: None
- **Key decisions**: User chose env-var approach for TS-39 (Option 2) and error-handler approach for TS-40 (Option 1)
