# Implementation Plan -- Fix Cycle 5 (ESCALATE Fixes)

## Requirements

| ID  | Requirement | Type | Priority | Source |
|-----|-------------|------|----------|--------|
| R31 | Status code mismatch: renderer must check `session_key_expired` not `expired` | functional (bug) | critical | TS-31 |
| R32 | Dockerfile must not run as root -- add non-root user | non-functional (security) | critical | TS-32 |
| R33 | Shell injection via filename in pidfile interpolation must be eliminated | non-functional (security) | high | TS-33 |
| R34 | Context hook must use atomic writes (tmp+rename), not bare writeFileSync | non-functional (reliability) | high | TS-34 |
| R35 | Legacy quota scripts must be removed from repo and install.sh | functional (cleanup) | high | TS-35 |
| R37 | Server config must reject --interval values below 30 seconds | non-functional (safety) | medium | TS-37 |
| R-NR | All 362 existing tests must continue to pass (zero regression) | non-functional (quality) | critical | constraint |

## Task Waves

### Wave 1 (parallel -- no dependencies between tasks)

#### T1.1: Fix status code mismatch AND shell injection in tmux-claude-status
- **Requirement(s)**: R31, R33
- **Rationale for combining**: Both modify `scripts/tmux-claude-status`. Separate tasks would create a merge conflict. Combined, the edit is still small (~15 min).
- **Acceptance criteria**:
  - [ ] Line 298 case pattern includes `session_key_expired` (literal string match in the file)
  - [ ] The case pattern on line 298 no longer contains bare `expired` as a standalone alternative (it may appear as part of `session_key_expired` or `key_expired`)
  - [ ] Lines 22 and 27 (pidfile reads) pass the path via `sys.argv` instead of string interpolation: the python3 invocations must use `sys.argv[1]` and the shell must pass `"$pidfile"` as a positional argument
  - [ ] No occurrence of `open('$pidfile')` or `open("$pidfile")` remains in the file
  - [ ] The script remains executable (`test -x scripts/tmux-claude-status` returns 0)
  - [ ] `bash -n scripts/tmux-claude-status` exits 0 (no syntax errors)
- **Expected files**: `scripts/tmux-claude-status`
- **Estimated scope**: small

#### T1.2: Add non-root user to Dockerfile
- **Requirement(s)**: R32
- **Acceptance criteria**:
  - [ ] `server/Dockerfile` contains a `RUN` instruction that creates a user (e.g., `useradd -r -s /usr/sbin/nologin appuser` or equivalent)
  - [ ] `server/Dockerfile` contains a `USER appuser` directive (or whatever username was created)
  - [ ] The `USER` directive appears after `RUN pip install` and before `ENTRYPOINT`
  - [ ] `server/tests/test_deploy.py` contains a test class or test method that verifies the Dockerfile has a `USER` directive specifying a non-root user
  - [ ] `python3 -m pytest server/tests/test_deploy.py -v` passes with 0 failures
- **Expected files**: `server/Dockerfile`, `server/tests/test_deploy.py`
- **Estimated scope**: small

#### T1.3: Make context hook use atomic writes
- **Requirement(s)**: R34
- **Acceptance criteria**:
  - [ ] `scripts/tmux-status-context-hook.js` does NOT contain a bare `writeFileSync(bridgePath, ...)` call that writes directly to the final path
  - [ ] The file contains a write to a temporary path (e.g., `bridgePath + '.tmp'` or similar) followed by `renameSync` to the final `bridgePath`
  - [ ] `node -c scripts/tmux-status-context-hook.js` exits 0 (no syntax errors)
  - [ ] The script remains executable (`test -x scripts/tmux-status-context-hook.js` returns 0)
- **Expected files**: `scripts/tmux-status-context-hook.js`
- **Estimated scope**: small

#### T1.4: Remove legacy quota scripts from repo and install.sh
- **Requirement(s)**: R35
- **Acceptance criteria**:
  - [ ] `scripts/tmux-status-quota-fetch` does not exist (verified by `test ! -f scripts/tmux-status-quota-fetch`)
  - [ ] `scripts/tmux-status-quota-poll` does not exist (verified by `test ! -f scripts/tmux-status-quota-poll`)
  - [ ] `install.sh` SCRIPTS array does not contain `tmux-status-quota-fetch`
  - [ ] `install.sh` SCRIPTS array does not contain `tmux-status-quota-poll`
  - [ ] `bash -n install.sh` exits 0 (no syntax errors)
  - [ ] The install.sh SCRIPTS array still contains the 5 remaining scripts: `tmux-claude-status`, `tmux-git-status`, `tmux-status-apply-config`, `tmux-status-session`, `tmux-status-context-hook.js`
- **Expected files**: `scripts/tmux-status-quota-fetch` (deleted), `scripts/tmux-status-quota-poll` (deleted), `install.sh`
- **Estimated scope**: small

#### T1.5: Add interval lower bound validation in server config
- **Requirement(s)**: R37
- **Acceptance criteria**:
  - [ ] `server/tmux_status_server/config.py` `parse_args()` function rejects `--interval` values less than 30 with a parser error (calls `parser.error(...)`)
  - [ ] `parse_args(["--interval", "29"])` raises `SystemExit` (argparse parser.error behavior)
  - [ ] `parse_args(["--interval", "30"])` succeeds and returns `args.interval == 30`
  - [ ] `parse_args(["--interval", "1"])` raises `SystemExit`
  - [ ] `server/tests/test_config.py` contains at least one test that verifies `--interval 29` is rejected
  - [ ] `server/tests/test_config.py` contains at least one test that verifies `--interval 30` is accepted
  - [ ] `python3 -m pytest server/tests/test_config.py -v` passes with 0 failures
- **Expected files**: `server/tmux_status_server/config.py`, `server/tests/test_config.py`
- **Estimated scope**: small

### Wave 2 (depends on all Wave 1 tasks)

#### T2.1: Full regression test run
- **Depends on**: T1.1, T1.2, T1.3, T1.4, T1.5
- **Requirement(s)**: R-NR
- **Acceptance criteria**:
  - [ ] Running the full test suite (all tests under `server/tests/`) passes with 0 failures and at least 362 tests
  - [ ] `bash -n scripts/tmux-claude-status` exits 0
  - [ ] `bash -n install.sh` exits 0
  - [ ] `node -c scripts/tmux-status-context-hook.js` exits 0
- **Expected files**: none (verification only)
- **Estimated scope**: small

## Requirement Traceability

| Requirement | Tasks | Coverage |
|-------------|-------|----------|
| R31: Status code mismatch | T1.1 | full |
| R32: Dockerfile runs as root | T1.2 | full |
| R33: Shell injection via filename | T1.1 | full |
| R34: Non-atomic writeFileSync | T1.3 | full |
| R35: Legacy scripts still shipped | T1.4 | full |
| R37: No interval lower bound | T1.5 | full |
| R-NR: Zero regression | T2.1 | full |

## Test Strategy

- **T1.1**: Verified by grep/content checks (no dedicated unit test needed; the fix is a string literal change and a shell argument passing change). `bash -n` confirms syntax.
- **T1.2**: New test(s) in `test_deploy.py` check for USER directive. Full pytest run confirms no regression.
- **T1.3**: `node -c` syntax check confirms JS validity. Grep confirms atomic pattern (tmp + rename).
- **T1.4**: File existence checks (negative) and grep on install.sh SCRIPTS array.
- **T1.5**: New test(s) in `test_config.py` verify interval rejection. Full pytest run confirms no regression.
- **T2.1**: Full suite run catches any cross-cutting regressions.

## Resumption Points

After each wave, the codebase is in a consistent, testable state:

- **After Wave 1**: All 6 fixes are applied independently. Each file change is self-contained. If interrupted mid-wave, any completed task's changes are valid on their own -- no task in Wave 1 depends on another Wave 1 task.
- **After Wave 2**: Full regression validated. Ready for commit.

**If interrupted during Wave 1**: Check which tasks are done by running their acceptance criteria. Resume the remaining Wave 1 tasks (they are independent).

## Risk Register

| Risk | Impact | Mitigation |
|------|--------|-----------|
| T1.1 case pattern change breaks other status values (blocked, rate_limited, etc.) | High -- quota status display broken for all error states | Acceptance criteria explicitly verify the full case pattern retains all other values. The change only adds `session_key_expired` and removes bare `expired`. |
| T1.2 USER directive placement breaks pip install (if placed before RUN pip) | Medium -- Docker build fails | Acceptance criteria require USER after pip install and before ENTRYPOINT. |
| T1.4 removing scripts breaks something that imports/references them | Medium -- broken install or runtime | The install.sh already has a "kill old quota-poll" migration block (lines 240-244); that block references `tmux-status-quota-poll` via pgrep pattern, not the script file itself, so removal is safe. The renderer (`tmux-claude-status`) does not reference these scripts. |
| T1.5 interval validation breaks existing tests that use low intervals | Medium -- test regression | Review existing test_config.py tests: `test_custom_interval` uses 60 (above 30, safe). `test_all_args_combined` uses 60 (safe). No existing test uses an interval below 30. |
| T1.1 sys.argv refactor breaks the line-27 cwd read if not updated symmetrically | High -- Claude session detection fails silently | Acceptance criteria require BOTH line 22 and line 27 to be updated. |

## Scope Boundaries

**IN scope**:
- The 6 specific fixes described in the stories (TS-31, TS-32, TS-33, TS-34, TS-35, TS-37)
- New tests for T1.2 and T1.5 (required to verify the fixes)
- Full regression run

**OUT of scope**:
- Any refactoring beyond the minimum needed for each fix
- Adding tests for T1.1/T1.3/T1.4 beyond syntax checks (the fixes are trivial string/pattern changes)
- Updating CLAUDE.md or README to reflect removed scripts
- Updating uninstall.sh to stop removing legacy scripts (it handles missing files gracefully)
- Any other ESCALATE items not listed in the 6 stories above

## Deviation Log

| Task | Planned | Actual | Impact | Decision |
|------|---------|--------|--------|----------|
| (empty -- will be filled during execution) | | | | |
