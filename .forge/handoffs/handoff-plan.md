# Handoff: Plan -> Decompose (Fix Cycle 6)

## Summary
Implementation plan created for 2 ESCALATE items (TS-39, TS-40). Plan approved by user.

## Key Decisions
- TS-39: Env var approach chosen (pass TRANSCRIPT via environment, read with os.environ)
- TS-40: Add @app.error(401) handler matching existing 404/500 pattern
- Plan has 2 parallel Wave 1 tasks + 1 verification Wave 2 task
- Error message in 401 handler: "invalid_or_missing_api_key" (matches existing check_auth abort call and tests)

## Task Summary
- T1.1: Fix $TRANSCRIPT shell interpolation in tmux-claude-status (TS-39)
- T1.2: Add @app.error(401) JSON handler to server (TS-40)
- T2.1: Full regression run (406+ tests, verification only)

## Context for Next Step (Decompose)
- 2 ESCALATE stories already exist in storyhook: TS-39, TS-40
- These stories need updating with acceptance criteria from the plan, NOT new story creation
- T2.1 is a verification gate, not a story — handled by the evaluator during execution
- Wave 1 is fully parallel — both tasks can execute concurrently

## Pipeline State
- Fix cycle: 6 (ESCALATE resolution cycle)
- Yolo: false
- Max fix cycles: 3 (exceeded, operating in ESCALATE mode)
- Tests: 406 passing (baseline)
- Stories to fix: 2 (TS-39, TS-40)

## Open Questions
- None — plan approved as-is
