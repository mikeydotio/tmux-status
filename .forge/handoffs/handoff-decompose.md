# Handoff: decompose -> execute (ESCALATE Fix Cycle 3)

## Summary
Mapped PLAN.md to existing ESCALATE stories. 4 stories across 2 waves, plus regression validation.

## Key Decisions
- Reused existing ESCALATE stories (TS-12, TS-13, TS-22, TS-23) rather than creating new ones
- Created TS-30 as parent story for this execution cycle
- TS-13 blocked-by TS-22 (both modify server.py; land smaller change first)

## Story-to-Task Mapping

| Story | Task | Priority | Wave | Files |
|-------|------|----------|------|-------|
| TS-12 | T1.1: Remove unused imports | high | 1 | `__main__.py`, `test_package.py`, `test_server.py` |
| TS-22 | T1.2: SIGTERM raises SystemExit | high | 1 | `server.py`, `test_server.py` |
| TS-23 | T1.3: Polyglot extraction harness | medium | 1 | `test_polyglot_extract.py` (new), `test_validate_gaps.py` |
| TS-13 | T2.1: Refactor _org_uuid | high | 2 | `scraper.py`, `server.py`, `test_scraper.py`, `test_server.py`, `test_validate_gaps.py` |

## Context for Next Step (Execute)
- **Wave 1** (3 stories, parallel): TS-12, TS-22, TS-23 — all independent
- **Wave 2** (1 story, sequential): TS-13 — blocked by TS-22
- API design decided: `fetch_quota(session_key, org_uuid=None)` -> `(result, new_org_uuid)`
- Baseline: 309 tests passing, 0 failures
- Design sections embedded in plan-mapping.json for generator context

## Pipeline State
- Fix cycle: 3 (ESCALATE fixes)
- Yolo mode: false
- Parent story: TS-30

## Open Questions
None — all tasks have clear acceptance criteria and user-approved approaches.
