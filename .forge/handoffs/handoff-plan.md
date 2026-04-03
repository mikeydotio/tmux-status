# Handoff: Plan → Decompose

## Timestamp
2026-04-03T15:30:00Z

## Artifacts Produced
- `.forge/PLAN.md` — Full implementation plan with 8 tasks across 3 waves, approved by user

## Key Decisions

1. **8 tasks, 3 waves** — Wave 1 has 5 parallel tasks (config, scraper, settings, packaging, deploy files), Wave 2 has 2 tasks (server HTTP module + client fetch), Wave 3 has 2 tasks (install + uninstall modifications).

2. **24 requirements traced** — Every requirement from IDEA.md and DESIGN.md is mapped to at least one task (R1-R24).

3. **Critical skeptic findings incorporated:**
   - T2.2 includes "X%" error display handling (renderer shows "X%" on error statuses, not silent "0%")
   - T3.1 includes old poller migration (kills running `tmux-status-quota-poll` processes on upgrade)
   - T2.1 requires immediate first scrape on startup (no 300s delay for first data)
   - T2.1 requires re-reading session key file on every scrape cycle (key rotation without restart)

4. **Test suite is OUT of scope** — QA designed a strategy (pytest + webtest, ~60 cases) but it's deferred to a future phase. Documented in PLAN.md for reference.

5. **Deprecated scripts left in place** — `tmux-status-quota-fetch` and `tmux-status-quota-poll` are not deleted, just deprecated.

## Context for Next Step

### Plan Structure
- **Wave 1 (parallel):** T1.1 config, T1.2 scraper, T1.3 settings+gitignore, T1.4 packaging, T1.5 deploy files
- **Wave 2:** T2.1 server HTTP (depends T1.1, T1.2, T1.4) — CRITICAL PATH, largest task; T2.2 client fetch (depends T1.3)
- **Wave 3:** T3.1 install.sh (depends T2.1, T1.5); T3.2 uninstall.sh (depends T2.1, T1.5)

### Task Dependencies
```
T1.1 ──┐
T1.2 ──┤
T1.4 ──┼──► T2.1 ──┬──► T3.1
T1.5 ──┤           └──► T3.2
T1.3 ──┼──► T2.2
```

### Complexity Notes
- T2.1 (server.py) is the largest task — wires together config, scraper, and packaging into a running server with auth, threads, signals
- T1.2 (scraper.py) is a medium-complexity extraction from the existing 287-line `tmux-status-quota-fetch`
- All Wave 1 tasks are small and independent — maximum parallelism

### Acceptance Criteria Quality
All criteria are machine-evaluable (file exists, function present, specific behavior observable in code diff). No subjective criteria.

## Pipeline State
- Fix cycle: 0 / 3
- Yolo mode: false
- Team roster: software-architect, security-researcher, devils-advocate (all active)
- ESCALATE stories pending: 0
- Plan approved by user

## Open Questions for Decomposition
- How to size stories for T2.1 (server HTTP module) — it's the largest task. May need sub-stories.
- Story priority ordering within each wave — all Wave 1 stories can be parallel.
