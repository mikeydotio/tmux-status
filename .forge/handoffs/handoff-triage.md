# Handoff: Triage -> Plan (Fix Loop)

## Summary
Triaged 15 findings (11 review + 4 validation): 7 FIX, 3 ESCALATE, 5 no-action. Fix cycle 0/3, yolo=false.

## Key Decisions

1. **7 FIX items need code changes** — all are low-risk, localized fixes:
   - FIX-1: pyproject.toml build backend → `setuptools.build_meta` (1-line, Critical)
   - FIX-2: launchd plist tilde → sed substitution in install.sh (Critical)
   - FIX-3: Renderer status gap → else clause for non-ok statuses (Important)
   - FIX-4: Dockerfile bind → CMD ["--host", "0.0.0.0"] (Important)
   - FIX-5: install.sh hardcoded path → use $INSTALL_DIR variable (Important)
   - FIX-6: warn_if_exposed → expand safe addresses (Useful)
   - FIX-7: Stale org UUID → reset on 401/403 (Important)

2. **3 ESCALATE stories created** — all non-blocking, user reviews post-document:
   - TS-11: QUOTA_API_KEY plaintext (security posture decision)
   - TS-12: Unused imports in __main__.py (test design decision)
   - TS-13: Module-level global state (architecture decision)

3. **5 findings dismissed** — informational/advisory, no action needed.

## Context for Next Step (Plan)

The plan step should create stories for the 7 FIX items. All fixes are independent and can be parallelized. Key scope boundaries:
- FIX-2: Only modify install.sh, NOT the template plist or its tests
- FIX-7: Only clear _org_uuid on 401/403, do NOT refactor into instance variable (that's ESCALATE-3)
- FIX-4: May need a test addition in test_deploy.py for the CMD line

## Pipeline State
- Fix cycle: 0 / 3
- Yolo mode: false
- ESCALATE stories pending: 3 (TS-11, TS-12, TS-13)
- Total stories: 13 (10 done + 3 ESCALATE todo)

## Artifacts
- `.forge/TRIAGE.md` — full triage report with decisions and rationale
- `.storyhook/` — 3 new ESCALATE stories (TS-11, TS-12, TS-13) with structured context comments
