# Handoff: Plan (Fix Cycle 1) → Decompose

## Timestamp
2026-04-03T18:30:00Z

## Artifacts Produced
- `.forge/PLAN.md` — Fix cycle 1 plan with 7 tasks in 1 wave
- `.forge/fix-cycles/cycle-0/` — Archived original TRIAGE.md, PLAN.md, plan-mapping.json

## Key Decisions

1. **Plan approved by user** — all 7 FIX items in a single wave (all independent)
2. **No wave dependencies** — all tasks can be parallelized during decompose/execute
3. **FIX-2**: Only modify install.sh, NOT the template plist or its tests
4. **FIX-7**: Only clear _org_uuid on 401/403, do NOT refactor into instance variable

## Context for Next Step (Decompose)

7 tasks to decompose into stories, all in Wave 1:

- **T1.1** (Critical): `server/pyproject.toml` — change build-backend to `setuptools.build_meta`
- **T1.2** (Critical): `install.sh` — sed substitution to replace `~` with `$HOME` in launchd plist after copy
- **T1.3** (Important): `scripts/tmux-claude-status` — add else clause after `elif quota_status == "error"` setting pcts to "X"
- **T1.4** (Important): `server/Dockerfile` — add `CMD ["--host", "0.0.0.0"]` + test in test_deploy.py
- **T1.5** (Important): `install.sh` — change heredoc from `'TMUXLINE'` to `TMUXLINE`, use `$INSTALL_DIR/overlay/status.conf`
- **T1.6** (Useful): `config.py` — check `args.host not in ("127.0.0.1", "localhost", "::1")` + update test_config.py
- **T1.7** (Important): `scraper.py` — reset `_org_uuid = None` on 401/403 from usage endpoint + test in test_scraper.py

All tasks are independent — one story per task, all wave 1.

## Pipeline State
- Fix cycle: 1 / 3
- Yolo mode: false
- ESCALATE stories pending: 3 (TS-11, TS-12, TS-13)
- Total stories: 13 (10 done + 3 ESCALATE todo)

## Open Questions
None — all fixes have clear, single-option solutions from triage.
