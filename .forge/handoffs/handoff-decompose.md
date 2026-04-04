# Handoff: Decompose (Fix Cycle 2) -> Execute

## Context

Fix cycle 2 plan decomposed into 4 task stories + 1 parent under TS-25. Wave dependencies enforced via storyhook blocked-by relationships.

## Key Decisions

1. **5 stories created** via `storyhook_decompose_spec`:
   - TS-25: Parent (Fix Cycle 2 — Work Execution)
   - TS-26: T1.1 — Auth bypass fix (critical, wave 1)
   - TS-27: T1.2 — Empty API key fix (critical, wave 1)
   - TS-28: T1.3 — Renderer None guard (high, wave 1)
   - TS-29: T2.1 — WSGI integration tests (high, wave 2)

2. **7 relationships**: 4 child-of + 3 blocked-by (TS-29 blocked by all wave 1 stories)

3. **DAG validated**: No cycles. Critical path: TS-28 -> TS-29.

## Story-to-Task Mapping

| Story | Task | Priority | Wave | Files |
|-------|------|----------|------|-------|
| TS-26 | T1.1: Auth bypass abort(401) | critical | 1 | `server/tmux_status_server/server.py` |
| TS-27 | T1.2: Empty API key returns None | critical | 1 | `server.py`, `test_server.py`, `test_validate_gaps.py` |
| TS-28 | T1.3: Renderer None guard | high | 1 | `scripts/tmux-claude-status` |
| TS-29 | T2.1: WSGI integration tests | high | 2 | `server/tests/test_server.py` |

## Context for Next Step (Execute)

- **Wave 1** (3 stories, parallel): TS-26, TS-27, TS-28 — all independent
- **Wave 2** (1 story, sequential): TS-29 — depends on all wave 1 completions
- `webtest` 3.0.7 and `bottle` 0.13.4 already in venv
- Mock tests in TestAuthHook need updating when check_auth raises instead of returns (part of TS-26)
- test_server.py has TestApiKeyEdgeCases at line 1083+ needing assertion changes (part of TS-27)
- test_validate_gaps.py has TestEmptyApiKeySecurityFinding at line 379+ needing updates (part of TS-27)
- All acceptance criteria embedded as storyhook comments on each story
- Design sections embedded in plan-mapping.json for generator context

## Pipeline State

- Fix cycle: 2 / 3 (max)
- Yolo mode: false
- ESCALATE stories pending: 5 (TS-11, TS-12, TS-13, TS-22, TS-23)
- Task stories this cycle: 4 (TS-26 through TS-29)
- All 292+ existing tests passing

## Open Questions

None — all tasks have clear acceptance criteria and file targets.
