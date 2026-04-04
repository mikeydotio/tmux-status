# Handoff: Triage -> Plan (Pass 2, Fix Cycle 2)

## Context

Second triage pass after fix cycle 1 resolved 7 findings and review+validate pass 2 surfaced 9 findings (8 review, 3 validate with 2 overlaps). Triager agent deliberated on each finding with risk assessment.

## Key Decisions

1. **4 FIX items assigned** for fix cycle 2:
   - Auth bypass: `abort(401)` instead of `return` in check_auth hook (Critical)
   - Auth integration tests: real HTTP tests proving auth blocks data leakage (Critical)
   - Renderer None guard: `if fh_util is None or fh_util == "X"` at lines 189/193 (Important)
   - Empty API key bypass: `_load_api_key()` returns None for empty keys (Critical)

2. **2 new ESCALATE stories created**:
   - TS-22: SIGTERM doesn't shut down HTTP server (Important) — multiple valid shutdown strategies
   - TS-23: Client _maybe_fetch_quota embedded in polyglot (Important) — architectural decision

3. **3 DEFER items** (no stories): pip stderr suppression, _error_bridge naming, API key permission check. All Useful severity, low impact.

4. **Prior ESCALATE stories carried forward**: TS-11, TS-12, TS-13 (unchanged)

## Context for Next Step (Plan)

The plan step should create stories for these 4 FIX items. Key implementation notes:

- **Auth bypass fix** (server.py:74-84): Change `return json.dumps({"error": "invalid_or_missing_api_key"})` to `abort(401, json.dumps({"error": "invalid_or_missing_api_key"}))`. Remove the `response.status = 401` and `response.content_type` lines since abort() handles status. Consider adding an `@app.error(401)` handler for JSON content-type.
- **Auth integration tests** (test_server.py): Use `webtest.TestApp(app)` or Bottle's WSGI `__call__` interface. Verify: valid key → 200 with data, wrong key → 401 without data, missing key → 401 without data, /health → 200 always.
- **Renderer None guard** (scripts/tmux-claude-status:189,193): Two-line change, add `is None or` to existing `== "X"` checks.
- **Empty key fix** (server.py:56-64): After `f.read().strip()`, check `if not key: return None` with WARNING log. Update TestEmptyApiKeySecurityFinding tests.

All 4 fixes are localized, low-risk, and can be implemented in a single wave.

## Pipeline State
- Fix cycle: 2 / 3 (max)
- Yolo mode: false
- ESCALATE stories pending: 5 (TS-11, TS-12, TS-13, TS-22, TS-23)
- Total FIX items this cycle: 4
- All 292 existing tests passing

## Artifacts
- `.forge/TRIAGE.md` — full triage report with 4 FIX, 2 ESCALATE, 3 DEFER
- `.storyhook/` — 2 new ESCALATE stories (TS-22, TS-23) with structured context comments
