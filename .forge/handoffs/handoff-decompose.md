# Handoff: decompose -> execute (ESCALATE Fix Cycle 5)

## Summary
6 existing ESCALATE stories mapped to 5 tasks (TS-31 + TS-33 combined into T1.1). All in Wave 1 — fully parallel, no inter-task dependencies. Parent story TS-38. T2.1 (regression gate) is verification-only, not a story.

## Key Decisions
- Reused existing ESCALATE stories (TS-31, TS-32, TS-33, TS-34, TS-35, TS-37) — no new story creation
- TS-31 + TS-33 combined into task T1.1 (both edit tmux-claude-status, avoids merge conflict)
- TS-36 already done (accepted as moot in escalate review) — not included
- Parent story TS-38 created with parent-of relationships to all 6 stories
- Acceptance criteria added as comments on each story

## Story-to-Task Mapping

| Story | Task | Priority | Wave | Files |
|-------|------|----------|------|-------|
| TS-31 + TS-33 | T1.1: Status code mismatch + shell injection | critical+high | 1 | `scripts/tmux-claude-status` |
| TS-32 | T1.2: Non-root Dockerfile user | critical | 1 | `server/Dockerfile`, `server/tests/test_deploy.py` |
| TS-34 | T1.3: Atomic writes in context hook | high | 1 | `scripts/tmux-status-context-hook.js` |
| TS-35 | T1.4: Remove legacy scripts | high | 1 | `scripts/tmux-status-quota-fetch` (del), `scripts/tmux-status-quota-poll` (del), `install.sh` |
| TS-37 | T1.5: Interval lower bound validation | medium | 1 | `server/tmux_status_server/config.py`, `server/tests/test_config.py` |

## Context for Next Step (Execute)
- All 6 stories are in `todo` state, ready for execution
- Wave 1 is fully parallel — generator can pick any story
- TS-31 and TS-33 MUST be executed together (same file, same task T1.1)
- T2.1 regression gate (362+ tests) runs after all Wave 1 tasks complete
- TS-24 and TS-25 are stale parent stories from fix cycle 2 — ignore them
- Design sections embedded in plan-mapping.json — no need to read DESIGN.md during execution

## Pipeline State
- Fix cycle: 5 (ESCALATE cycle)
- Yolo mode: false
- Parent story: TS-38
- Stories to execute: 6 (5 tasks)
- Wave structure: Wave 1 (all parallel), Wave 2 (verification only)
- Tests baseline: 362 passing
- DAG: valid, no cycles

## Open Questions
None — all tasks have clear acceptance criteria and user-approved approaches.
