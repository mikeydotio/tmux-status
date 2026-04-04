# Handoff: Plan (Fix Cycle 2) -> Decompose

## Context

Fix cycle 2 plan approved. 4 FIX items from triage pass 2, organized into 5 tasks across 2 waves.

## Key Decisions

1. **Wave 1 (3 tasks, parallel):**
   - T1.1: Auth bypass fix — `abort(401, ...)` replaces `return json.dumps(...)` in check_auth hook (server.py:74-84). Critical.
   - T1.2: Empty API key fix — `_load_api_key()` returns `None` for empty/whitespace files with WARNING log (server.py:55-64). Critical. Updates tests in test_server.py and test_validate_gaps.py.
   - T1.3: Renderer None guard — `is None or` added before `round()` at lines 189, 193 of tmux-claude-status. Important.

2. **Wave 2 (1 task, depends on Wave 1):**
   - T2.1: WSGI integration tests via `webtest.TestApp` — 5+ tests proving auth blocks data leakage at the Bottle pipeline level. Tests: valid key->200, wrong key->401 no data, missing key->401 no data, /health->200 always, no auth->200.

3. **Test strategy:** Update existing mock-based auth tests for HTTPError (abort), add WSGI integration tests as authoritative proof, structural tests remain.

## Context for Next Step (Decompose)

- All tasks are small (single-file or 2-3 file changes)
- `webtest` 3.0.7 and `bottle` 0.13.4 already in venv
- Mock tests in TestAuthHook will need updating when check_auth raises instead of returns
- test_server.py has existing TestApiKeyEdgeCases at line 1083+ that need assertion changes
- test_validate_gaps.py has TestEmptyApiKeySecurityFinding at line 379+ that needs updating

## Pipeline State
- Fix cycle: 2 / 3 (max)
- Yolo mode: false
- ESCALATE stories pending: 5 (TS-11, TS-12, TS-13, TS-22, TS-23)
- Total tasks this cycle: 5 (across 2 waves)
- All 292+ existing tests passing

## Open Questions
None — all fixes have clear solutions from triage.
