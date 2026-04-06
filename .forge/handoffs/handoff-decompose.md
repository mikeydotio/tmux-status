# Handoff: Decompose -> Execute (Fix Cycle 6)

## Summary
2 existing ESCALATE stories (TS-39, TS-40) updated with acceptance criteria and mapped to plan tasks. Both in Wave 1 — fully parallel, no dependencies. No new stories created.

## Key Decisions
- Reused existing ESCALATE stories (TS-39, TS-40) — no new story creation needed
- Both set to priority high
- Acceptance criteria added as structured JSON comments on each story
- No parent story needed (only 2 stories)
- Design sections embedded in plan-mapping.json

## Story-to-Task Mapping

| Story | Task | Priority | Wave | Files |
|-------|------|----------|------|-------|
| TS-39 | T1.1: Fix $TRANSCRIPT shell interpolation | high | 1 | `scripts/tmux-claude-status` |
| TS-40 | T1.2: Add @app.error(401) JSON handler | high | 1 | `server/tmux_status_server/server.py`, `server/tests/test_server.py` |

## Context for Next Step (Execute)
- Both stories are in `todo` state, ready for execution
- Wave 1 is fully parallel — generator can pick either story
- T2.1 regression gate (406+ tests) runs after both Wave 1 tasks complete
- TS-24 and TS-25 are stale parent stories from earlier cycles — ignore them
- Design sections embedded in plan-mapping.json — no need to read DESIGN.md during execution

## Pipeline State
- Fix cycle: 6 (ESCALATE resolution cycle)
- Yolo mode: false
- Stories to execute: 2
- Wave structure: Wave 1 (both parallel), Wave 2 (verification only)
- Tests baseline: 406 passing
- DAG: valid, no cycles

## Open Questions
None — all tasks have clear acceptance criteria and user-approved approaches.
