# Handoff: Decompose (Fix Cycle 1) → Execute

## Timestamp
2026-04-04T01:10:00Z

## Artifacts Produced
- `.forge/plan-mapping.json` — 7 fix stories mapped to DESIGN.md sections
- Storyhook stories TS-15 through TS-21 created under parent TS-14

## Key Decisions

1. **Single wave, all independent** — no dependency edges between fix stories
2. **Parent story TS-14** — "Fix Cycle 1 — Work Execution" groups all 7 fixes
3. **DAG validated** — no cycles detected, all stories are roots and leaves

## Story-to-Task Mapping

| Story | Task | Priority | Files |
|-------|------|----------|-------|
| TS-15 | T1.1: pyproject.toml build backend | critical | `server/pyproject.toml` |
| TS-16 | T1.2: launchd plist tilde expansion | critical | `install.sh` |
| TS-17 | T1.3: renderer status fallthrough | high | `scripts/tmux-claude-status` |
| TS-18 | T1.4: Dockerfile bind address | high | `server/Dockerfile`, `server/tests/test_deploy.py` |
| TS-19 | T1.5: install.sh hardcoded path | high | `install.sh` |
| TS-20 | T1.6: warn_if_exposed safe addresses | medium | `server/tmux_status_server/config.py`, `server/tests/test_config.py` |
| TS-21 | T1.7: stale org UUID on auth errors | high | `server/tmux_status_server/scraper.py`, `server/tests/test_scraper.py` |

## Context for Next Step (Execute)

- All 7 stories are `todo` state, wave 1, no blockers
- ESCALATE stories (TS-11, TS-12, TS-13) remain `todo` — not part of this fix cycle
- Each fix is small (1-5 lines of code change + test updates)
- Run `cd server && python -m pytest` after server-side fixes to verify no regressions

## Pipeline State
- Fix cycle: 1 / 3
- Yolo mode: false
- Total stories: 21 (10 done from original + 3 ESCALATE + 1 parent + 7 fix cycle)

## Open Questions
None — all fixes have clear single-option solutions from triage.
