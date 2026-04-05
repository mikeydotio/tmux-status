# Handoff: escalate-review -> plan

## Summary
Completed ESCALATE review loop with user. 7 ESCALATE stories reviewed: 6 to fix, 1 accepted (TS-36, moot due to TS-35 file deletion).

## User Decisions

### TS-31 (Critical): Status code mismatch — FIX
Replace `expired` with `session_key_expired` in renderer. No backward compatibility — just use the new code. Server already sends `session_key_expired` for HTTP 401.

### TS-32 (Critical): Dockerfile runs as root — FIX
Add non-root user in Dockerfile: `RUN useradd -r -s /usr/sbin/nologin appuser` + `USER appuser`. Standard security practice, no downside for this project.

### TS-33 (Important): Shell injection via filename — FIX
Pass pidfile via sys.argv: `python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['pid'])" "$pidfile"`. Same dependency footprint, complete fix.

### TS-34 (Important): Context hook non-atomic write — FIX
Add temp+rename pattern to `tmux-status-context-hook.js:55`. Write to `.tmp` then `renameSync`. Consistent with project convention.

### TS-35 (Important): Legacy scripts still shipped — FIX
Remove deprecated `tmux-status-quota-fetch` and `tmux-status-quota-poll` from install.sh SCRIPTS array. **Also delete the script files entirely** — user confirmed git history is sufficient. Remove `tmux-status-quota-poll` as well.

### TS-36 (Important): Old fetch script exposes raw exception text — ACCEPTED
Moot — TS-35 deletes the files entirely. No action needed.

### TS-37 (Medium): No interval lower bound validation — FIX
Add `if args.interval < 30: parser.error(...)` in parse_args(). Clear error message. Matches old MIN_INTERVAL=30 behavior.

## Context for Next Step (Plan)
- Fix cycle: 5 (ESCALATE cycle 4 fixes)
- Archived cycle-4 artifacts: TRIAGE.md, PLAN.md, plan-mapping.json, REVIEW-REPORT.md, VALIDATE-REPORT.md, DOCUMENTATION.md
- 6 stories need planning: TS-31, TS-32, TS-33, TS-34, TS-35, TS-37
- TS-36 accepted (moot due to TS-35)
- Tests: 362 passing, 0 failures (baseline)
- DOCUMENTATION.md archived — needs regeneration after fixes

## Pipeline State
- Yolo: false
- Max fix cycles: 3 (exceeded, operating in ESCALATE mode)
- Current fix cycle: 4 (ESCALATE)
- Stories to fix: 6
- Stories accepted: 1 (TS-36)

## Artifacts Archived to fix-cycles/cycle-4/
- TRIAGE.md
- PLAN.md
- plan-mapping.json
- REVIEW-REPORT.md
- VALIDATE-REPORT.md
- DOCUMENTATION.md
