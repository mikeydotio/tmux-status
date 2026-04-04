# Implementation Plan -- ESCALATE Fix Cycle (Cycle 3)

## Requirements

| ID  | Requirement | Type | Priority | Story |
|-----|-------------|------|----------|-------|
| R1  | Remove unused `parse_args` and `warn_if_exposed` imports from `__main__.py` | functional | high | TS-12 |
| R2  | Update/remove tests in `test_package.py` that assert those imports exist in `__main__.py` | functional | high | TS-12 |
| R3  | Eliminate module-level global `_org_uuid` from `scraper.py` | functional | high | TS-13 |
| R4  | Move `_org_uuid` state into `QuotaServer` and thread it through to `fetch_quota` | functional | high | TS-13 |
| R5  | Update all test setUp calls that reset `scraper._org_uuid = None` to use the new mechanism | functional | high | TS-13 |
| R6  | Preserve existing org UUID caching semantics (cache on success, clear on 401/403, skip discovery when cached) | non-functional | high | TS-13 |
| R7  | `_handle_sigterm` must actually terminate the process via `raise SystemExit(0)` | functional | high | TS-22 |
| R8  | Add test proving SIGTERM handler raises `SystemExit` instead of just setting flags | functional | high | TS-22 |
| R9  | Build test harness that extracts Python code from polyglot `tmux-claude-status` and tests it directly | functional | high | TS-23 |
| R10 | Replace re-implemented `_maybe_fetch_quota_impl` in `test_validate_gaps.py` with extracted real code | functional | high | TS-23 |
| R11 | All 309+ existing tests must continue to pass after changes | non-functional | high | all |
| R12 | No regressions in the server module's import structure (AST tests) | non-functional | medium | all |

## Task Waves

### Wave 1 (parallel -- no dependencies)

#### T1.1: TS-12 -- Remove unused imports and fix tests in __main__.py

- **Requirement(s)**: R1, R2, R12
- **Acceptance criteria**:
  - [ ] `server/tmux_status_server/__main__.py` does NOT contain `from tmux_status_server.config import parse_args, warn_if_exposed` (or any import of those names)
  - [ ] `server/tmux_status_server/__main__.py` still defines `main()` that calls `_server_main()` and has `if __name__ == "__main__"` guard
  - [ ] `server/tests/test_package.py` class `TestMainModule`:
    - `test_main_calls_parse_args` is removed or updated to assert `parse_args` is NOT in the source
    - `test_main_calls_warn_if_exposed` is removed or updated to assert `warn_if_exposed` is NOT in the source
    - `test_main_imports_config` is removed or updated to assert config imports are NOT present
  - [ ] `server/tests/test_server.py` class `TestMainModuleUpdated`:
    - `test_still_imports_config` (line 307-315) is removed or updated to NOT assert config imports exist in `__main__.py`
  - [ ] Running `python -m pytest server/tests/test_package.py` passes with 0 failures
  - [ ] Running `python -m pytest server/tests/test_server.py::TestMainModuleUpdated` passes with 0 failures
- **Expected files**: `server/tmux_status_server/__main__.py`, `server/tests/test_package.py`, `server/tests/test_server.py`
- **Estimated scope**: small

#### T1.2: TS-22 -- Fix SIGTERM handler to raise SystemExit

- **Requirement(s)**: R7, R8
- **Acceptance criteria**:
  - [ ] `server/tmux_status_server/server.py` method `_handle_sigterm` sets `self._shutdown` and `self._wake` (belt-and-suspenders for daemon poll thread cleanup), then raises `SystemExit(0)`
  - [ ] `server/tests/test_server.py` class `TestSignalHandling`:
    - `test_sigterm_sets_shutdown` is updated: calling `_handle_sigterm(signal.SIGTERM, None)` raises `SystemExit` (use `assertRaises(SystemExit)`)
    - `test_sigint_sets_shutdown` is updated: calling `_handle_sigterm(signal.SIGINT, None)` raises `SystemExit`
    - New test `test_sigterm_raises_systemexit_with_code_zero` verifies the exit code is 0
  - [ ] The SIGUSR1 handler (`_handle_sigusr1`) is NOT changed -- it still sets `_wake` without raising
  - [ ] `server/tests/test_server.py::TestSignalHandling::test_sigusr1_sets_wake_not_shutdown` still passes unchanged
  - [ ] Running `python -m pytest server/tests/test_server.py::TestSignalHandling` passes with 0 failures
- **Expected files**: `server/tmux_status_server/server.py`, `server/tests/test_server.py`
- **Estimated scope**: small

#### T1.3: TS-23 -- Build polyglot extraction harness and replace re-implementation

- **Requirement(s)**: R9, R10
- **Acceptance criteria**:
  - [ ] A new test file `server/tests/test_polyglot_extract.py` (or section in `test_validate_gaps.py`) contains a helper function that:
    - Reads `scripts/tmux-claude-status` from disk
    - Extracts specifically the `_maybe_fetch_quota` function definition from the embedded Python block (NOT the full Python block, since bash `$TRANSCRIPT` interpolation makes the full block invalid standalone Python)
    - Keys off `def _maybe_fetch_quota` and extracts until the next module-level definition or dedent
    - Makes the extracted function callable in tests via `compile()` + `exec()` (use `compile(code, "tmux-claude-status:_maybe_fetch_quota", "exec")` for traceback clarity)
    - Includes a canary assertion that extracted function contains known strings (`urllib.request.Request`, `os.replace`) to detect extraction failures early
  - [ ] The extracted function is semantically equivalent to the current re-implementation in `test_validate_gaps.py`
  - [ ] At least one integration test calls the **extracted** function (not the re-implementation) against a local HTTP server and verifies it writes a valid JSON cache file
  - [ ] The `_maybe_fetch_quota_impl` re-implementation in `test_validate_gaps.py` is replaced with a call to the extraction helper, OR a comment/test documents that it matches the real code
  - [ ] Running `python -m pytest server/tests/test_polyglot_extract.py` (or equivalent) passes with 0 failures
  - [ ] `scripts/tmux-claude-status` is NOT modified
- **Expected files**: `server/tests/test_polyglot_extract.py` (new), `server/tests/test_validate_gaps.py` (modified)
- **Estimated scope**: medium

### Wave 2 (depends on Wave 1)

#### T2.1: TS-13 -- Refactor _org_uuid into QuotaServer instance state

- **Depends on**: T1.2 (both modify `server.py`; T1.2 is smaller and should land first to avoid merge conflicts)
- **Requirement(s)**: R3, R4, R5, R6
- **Acceptance criteria**:
  - [ ] `server/tmux_status_server/scraper.py`:
    - Module-level `_org_uuid = None` (line 21) is removed
    - `fetch_quota()` no longer uses `global _org_uuid`
    - **Concrete API design (decided):** `fetch_quota(session_key, org_uuid=None)` returns `(result_dict, new_org_uuid)` tuple. This keeps scraper.py stateless (no class needed) and puts ownership on QuotaServer. The `org_uuid` keyword arg maintains backward compatibility for any direct callers.
    - The caching logic is preserved: skip org discovery when org_uuid is provided, clear on 401/403, return discovered UUID on success
  - [ ] `server/tmux_status_server/server.py`:
    - `QuotaServer.__init__` initializes `self._org_uuid = None`
    - `QuotaServer._do_scrape` passes `self._org_uuid` to `fetch_quota` and stores the returned org_uuid back into `self._org_uuid`
    - On 401/403 error responses, `self._org_uuid` is reset to `None` (either by the server interpreting the result, or by fetch_quota returning `None` as the new org_uuid)
  - [ ] `server/tests/test_scraper.py`:
    - All `setUp` methods that do `scraper._org_uuid = None` are updated or removed
    - Tests in `TestOrgUuidCaching` and `TestOrgUuidResetOnAuthError` are updated to test via the new interface (pass org_uuid as argument, check returned value)
    - All assertions about `scraper._org_uuid` are replaced with assertions about the return value
  - [ ] `server/tests/test_server.py`:
    - Tests that verify `_do_scrape` behavior are updated to account for the new org_uuid flow through QuotaServer
  - [ ] Running `python -m pytest server/tests/test_scraper.py` passes with 0 failures
  - [ ] Running `python -m pytest server/tests/test_server.py` passes with 0 failures
  - [ ] `grep -r '_org_uuid' server/tmux_status_server/scraper.py` returns zero matches (no module-level global)
  - [ ] `grep -c 'global _org_uuid' server/tmux_status_server/scraper.py` returns 0
- **Expected files**: `server/tmux_status_server/scraper.py`, `server/tmux_status_server/server.py`, `server/tests/test_scraper.py`, `server/tests/test_server.py`
- **Estimated scope**: large

### Wave 3 (final validation)

#### T3.1: Full test suite regression check

- **Depends on**: T1.1, T1.2, T1.3, T2.1
- **Requirement(s)**: R11, R12
- **Acceptance criteria**:
  - [ ] `cd /home/mikey/tmux-status/server && python -m pytest tests/ -v` passes with 0 failures
  - [ ] Total test count is >= 309 (may increase due to new tests, must not decrease without documented reason)
  - [ ] No warnings about deprecated imports or module-level state leaks between test classes
  - [ ] `grep -r 'global _org_uuid' server/` returns zero matches across entire server directory
  - [ ] `grep -r 'scraper._org_uuid' server/tests/` returns zero matches (no test reaches into module global)
- **Expected files**: none (validation only)
- **Estimated scope**: small

## Requirement Traceability

| Requirement | Tasks | Coverage |
|-------------|-------|---------|
| R1: Remove unused imports from __main__.py | T1.1 | full |
| R2: Update/remove import-checking tests | T1.1 | full |
| R3: Eliminate module-level _org_uuid | T2.1 | full |
| R4: Move _org_uuid into QuotaServer | T2.1 | full |
| R5: Update test setUp for _org_uuid | T2.1 | full |
| R6: Preserve caching semantics | T2.1 | full |
| R7: SIGTERM raises SystemExit | T1.2 | full |
| R8: Test proving SystemExit on SIGTERM | T1.2 | full |
| R9: Polyglot extraction harness | T1.3 | full |
| R10: Replace re-implemented function | T1.3 | full |
| R11: Full test regression pass | T3.1 | full |
| R12: No import structure regressions | T1.1, T3.1 | full |

## Dependency Graph

```
T1.1 (TS-12) ──────────────────────────────┐
T1.2 (TS-22) ──> T2.1 (TS-13) ──> T3.1   │
T1.3 (TS-23) ──────────────────────> T3.1 ◄┘
```

- T1.1, T1.2, T1.3 are all independent of each other (Wave 1, parallel)
- T2.1 depends on T1.2 because both edit `server.py` -- T1.2 is a 3-line change, T2.1 is a large refactor; landing T1.2 first minimizes conflict surface
- T3.1 depends on all prior waves (full regression)

## Risks

| Risk | Impact | Mitigation |
|------|--------|-----------|
| T2.1 (TS-13) fetch_quota signature change breaks downstream callers | Any code calling `fetch_quota(session_key)` with positional arg breaks | Search entire codebase for `fetch_quota` callers before changing signature; use keyword-only `org_uuid=None` parameter for backward compat |
| T2.1 test_scraper.py has 14+ setUp calls resetting `scraper._org_uuid` | Missing one causes test pollution across test classes | Grep for ALL references to `scraper._org_uuid` and `_org_uuid` in test files before starting; build checklist |
| T1.3 polyglot extraction is fragile if script format changes | Extraction regex/marker detection may break silently | Include a canary assertion that the extracted function contains specific known strings (e.g., `urllib.request.Request`, `os.replace`) |
| T1.2 raising SystemExit in signal handler may affect tests that mock signal handling | Tests calling `_handle_sigterm` directly will get unexpected SystemExit | Update all direct callers to use `assertRaises(SystemExit)` |
| T1.1 removing test assertions may reduce coverage | Fewer tests on __main__.py | Verify remaining tests still cover: main() callable, delegates to server.main(), if-name-main guard, file exists |

## Scope Boundaries

**IN SCOPE:**
- Removing dead code (unused imports in `__main__.py`)
- Refactoring module-level mutable state to instance state (`_org_uuid`)
- Fixing a real bug (SIGTERM not terminating the server)
- Improving test fidelity (testing real polyglot code instead of re-implementation)
- Updating existing tests to match changed interfaces

**OUT OF SCOPE:**
- Changing the tmux-claude-status polyglot script itself (TS-23 is test-only)
- Adding new features to the server (quota endpoints, new routes)
- Refactoring other module-level state (e.g., REQUEST_HEADERS is fine as a constant)
- Performance optimization
- Any changes to the install/uninstall scripts
- Documentation updates beyond code comments

## Resumption Points

**After Wave 1 completes:**
- T1.1 done: `__main__.py` is clean, tests updated. Server.py untouched.
- T1.2 done: `_handle_sigterm` raises SystemExit. Signal tests updated.
- T1.3 done: Polyglot extraction harness exists and tests pass.
- Ready to start T2.1 (TS-13 refactor) which builds on T1.2's server.py state.

**After Wave 2 completes:**
- T2.1 done: `_org_uuid` is instance state on QuotaServer. No module globals. All scraper and server tests updated.
- Ready for T3.1 full regression.

**After Wave 3 completes:**
- All stories resolved. Full suite green. Ready for commit/PR.

## Deviation Log

| Task | Planned | Actual | Impact | Decision |
|------|---------|--------|--------|----------|
| (empty -- execution has not started) | | | | |
