# Handoff: Validate -> Triage (Pass 2)

## Summary
Test suite hardened from 235 to 292 tests (57 new in `test_validate_gaps.py`), all passing in 6.39s. Three findings identified: 1 Critical, 1 Important, 1 Known (TS-13).

## Key Decisions

1. **Client `_maybe_fetch_quota` tested via re-implementation**: The function is embedded in a bash/python polyglot script and cannot be imported. Tests use a re-implementation that matches the logic. Drift risk documented as FINDING-2.

2. **Real HTTP server for client tests**: All client integration tests use `http.server.HTTPServer` — no urllib mocking. This catches real HTTP behavior.

3. **Empty API key bypass confirmed**: `hmac.compare_digest("", "")` returns True. Test documents this as a security finding.

4. **All test files verified independently**: Each test file passes in isolation (no order dependencies).

## Findings for Triage

| # | Title | Severity | Action |
|---|-------|----------|--------|
| 1 | Empty API key file creates auth bypass | Critical | `_load_api_key` should return None for empty keys |
| 2 | Client _maybe_fetch_quota embedded in shell script | Important | Extract to importable module |
| 3 | Module-level _org_uuid global state | Important | Already tracked as TS-13 |

## Test Counts

| File | Count | Notes |
|------|-------|-------|
| test_config.py | 31 | Unchanged from pass 1 |
| test_scraper.py | 52 | Unchanged from pass 1 |
| test_package.py | existing | Unchanged |
| test_server.py | existing | Unchanged |
| test_deploy.py | existing | Unchanged |
| **test_validate_gaps.py** | **57** | **NEW — client integration, security, edge cases** |
| **Total** | **292** | All passing |

## Mock Audit
All mocks target external dependencies (curl_cffi, bottle, OS signals). New client tests use real HTTP server — no mocks.

## Artifacts
- `.forge/VALIDATE-REPORT.md` — full report with requirement coverage matrix
- `server/tests/test_validate_gaps.py` — 57 new tests
