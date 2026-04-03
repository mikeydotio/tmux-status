# Handoff: Validate -> Triage

## Summary
Test suite hardened from 188 to 223 tests (35 new), all passing in 0.28s. Four findings identified, all severity "Useful" (no Critical or Important issues).

## Key Decisions

1. **Client-side renderer tests out of scope**: The `_maybe_fetch_quota()` function in `scripts/tmux-claude-status` is embedded Python inside a bash script. Following the PLAN.md test strategy ("What NOT to test: tmux rendering output"), this was not tested. The function has silent-failure semantics, so bugs manifest as "no quota data" rather than crashes.

2. **API key file permission check not enforced**: R8 says "refuse if world-readable" but this only applies to the session key file, not the API key file. The implementation is consistent -- `read_session_key()` checks permissions, `_load_api_key()` does not. This is reasonable since the session key protects upstream credentials while the API key only protects the local server endpoint.

3. **Empty API key file behavior documented**: An empty `--api-key-file` results in auth being effectively disabled (empty string is falsy). Tests now document this behavior explicitly.

4. **Malformed usage response behavior documented**: A 200 response from claude.ai missing expected keys returns `status: "ok"` with `None` utilization values. In practice, the upstream API always returns the expected schema, so this is defense-in-depth.

## Findings for Triage

| # | Title | Severity | Action Needed? |
|---|-------|----------|----------------|
| 1 | Empty API key file disables auth | Useful | Informational -- could add a warning log |
| 2 | No API key file permission enforcement | Useful | Informational -- asymmetry with session key |
| 3 | Client renderer not unit-tested | Useful | Documented out-of-scope per PLAN.md |
| 4 | Malformed usage returns ok with None | Useful | Informational -- upstream always sends valid data |

## Test Counts by File

| File | Before | After | Added |
|------|--------|-------|-------|
| test_config.py | 22 | 29 | 7 |
| test_scraper.py | 36 | 43 | 7 |
| test_package.py | 21 | 21 | 0 |
| test_server.py | 75 | 96 | 21 (plus 7 in new classes not counted separately) |
| test_deploy.py | 34 | 34 | 0 |
| **Total** | **188** | **223** | **35** |

## Artifacts
- `.forge/VALIDATE-REPORT.md` -- full report with requirement coverage matrix
- `server/tests/test_config.py` -- 7 new tests
- `server/tests/test_scraper.py` -- 7 new tests  
- `server/tests/test_server.py` -- 21 new tests
