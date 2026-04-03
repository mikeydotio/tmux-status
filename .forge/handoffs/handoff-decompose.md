# Handoff: Decompose → Execute

## Timestamp
2026-04-03T19:06:00Z

## Artifacts Produced
- `.forge/plan-mapping.json` — Story-to-task mapping with embedded DESIGN.md sections
- `.storyhook/` — 10 stories (TS-1 parent + 9 work stories), 28 relationships

## Key Decisions

1. **9 work stories across 3 waves** — TS-2 through TS-10, all children of TS-1 (parent story).

2. **Wave-level dependencies (conservative):**
   - Wave 1 (TS-2..TS-6): No blockers, all ready immediately
   - Wave 2 (TS-7, TS-8): Blocked by ALL Wave 1 stories
   - Wave 3 (TS-9, TS-10): Blocked by ALL Wave 2 stories
   - Note: This is coarser than the per-task dependencies in PLAN.md (e.g., T2.2 only needs T1.3, not all of Wave 1). The conservative approach is safe for the one-story-at-a-time execution loop.

3. **Storyhook states added:** `verifying` and `blocked` states added to states.toml for the execution loop.

4. **DAG validated:** No cycles. Critical path: TS-6 → TS-7 → TS-10. Roots: TS-2..TS-6 (Wave 1). Leaves: TS-9, TS-10 (Wave 3).

5. **Design sections embedded** in plan-mapping.json. Each story carries the relevant DESIGN.md excerpt so the generator doesn't need to read DESIGN.md separately.

## Story-to-Task Mapping

| Story | Task | Wave | Priority | Files |
|-------|------|------|----------|-------|
| TS-2 | T1.1 Config module | 1 | high | `server/tmux_status_server/config.py` |
| TS-3 | T1.2 Scraper module | 1 | high | `server/tmux_status_server/scraper.py` |
| TS-4 | T1.3 Settings + gitignore | 1 | high | `config/settings.example.conf`, `.gitignore` |
| TS-5 | T1.4 Packaging + entry points | 1 | high | `server/tmux_status_server/__init__.py`, `__main__.py`, `pyproject.toml` |
| TS-6 | T1.5 Deployment files | 1 | medium | `server/deploy/` (3 files), `server/Dockerfile` |
| TS-7 | T2.1 Server HTTP module | 2 | critical | `server/tmux_status_server/server.py`, `__main__.py` |
| TS-8 | T2.2 Client HTTP fetch | 2 | high | `scripts/tmux-claude-status` |
| TS-9 | T3.1 Install script | 3 | high | `install.sh` |
| TS-10 | T3.2 Uninstall script | 3 | high | `uninstall.sh` |

## Context for Next Step

### Execution Order
The execution loop should process stories in priority order within each wave. Wave 1 has 5 stories all immediately ready — `story next` will surface them by priority. TS-7 (critical, Wave 2) is the largest and most complex story — it wires together config, scraper, and packaging into a running server.

### Critical Path
TS-7 (server HTTP module) is the bottleneck. It depends on 3 Wave 1 outputs (config, scraper, packaging) and blocks both Wave 3 stories. Getting TS-7 right on the first try is the single most impactful quality lever.

### Existing Code to Reference
- `scripts/tmux-status-quota-fetch` — Source of scraping logic for TS-3 (scraper module)
- `scripts/tmux-status-quota-poll` — Source of poll/signal patterns for TS-7 (server)
- `scripts/tmux-claude-status` — Modification target for TS-8 (client fetch)
- `config/settings.example.conf` — Modification target for TS-4 (settings)
- `install.sh` — Modification target for TS-9
- `uninstall.sh` — Modification target for TS-10

## Pipeline State
- Fix cycle: 0 / 3
- Yolo mode: false
- Team roster: software-architect, security-researcher, devils-advocate (all active)
- ESCALATE stories pending: 0
- All 9 work stories in `todo` state, Wave 1 ready for execution
