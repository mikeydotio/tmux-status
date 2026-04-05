# Handoff: plan -> decompose

## Summary
Fix cycle 5 (ESCALATE fixes) plan approved. 6 stories, 5 implementation tasks in Wave 1 (fully parallel), 1 regression gate in Wave 2.

## Key Decisions
- TS-31 + TS-33 combined into T1.1 (both edit tmux-claude-status, avoids merge conflict)
- All Wave 1 tasks are independent — can be decomposed into parallel stories
- TS-36 accepted as moot (covered by TS-35 file deletion) — no task needed
- User approved plan without modifications

## Task Summary
- T1.1: Fix status code mismatch + shell injection in tmux-claude-status (TS-31, TS-33)
- T1.2: Add non-root USER to Dockerfile (TS-32)
- T1.3: Atomic writes in context hook JS (TS-34)
- T1.4: Remove legacy quota scripts from repo + install.sh (TS-35)
- T1.5: Add --interval < 30 rejection in server config (TS-37)
- T2.1: Full regression run (362+ tests, verification only)

## Context for Next Step (Decompose)
- 6 ESCALATE stories already exist in storyhook: TS-31, TS-32, TS-33, TS-34, TS-35, TS-37
- These stories need updating with acceptance criteria from the plan, NOT new story creation
- T2.1 is a verification gate, not a story — handled by the evaluator during execution
- Wave 1 is fully parallel — all tasks can execute concurrently

## Pipeline State
- Fix cycle: 5 (ESCALATE cycle)
- Yolo: false
- Max fix cycles: 3 (exceeded, operating in ESCALATE mode)
- Tests: 362 passing (baseline)
- Stories to fix: 6 (TS-31, TS-32, TS-33, TS-34, TS-35, TS-37)
- Stories accepted: 1 (TS-36, moot)

## Open Questions
- None — plan approved as-is
