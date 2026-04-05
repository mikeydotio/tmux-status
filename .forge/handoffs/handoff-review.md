# Handoff: Review -> Triage

## Key Decisions

- **TS-33 fix is partial**: The pidfile injection was fixed correctly, but `$TRANSCRIPT` shell interpolation in the same heredoc (line 49) uses the identical vulnerable pattern. This is the same vulnerability class -- shell variable expanded into an unquoted heredoc that gets passed to `eval "$(python3 ...)"`. Practical risk is low (filenames are UUIDs controlled by Claude Code) but the inconsistency with the pidfile fix is notable.
- **401 response breaks JSON contract**: The Bottle `abort(401, ...)` call in `check_auth` produces HTML, not JSON, because there is no `@app.error(401)` handler. This violates the DESIGN.md spec that says all responses are `application/json`. The 404 and 500 cases are handled correctly.
- **Overall alignment is good**: The codebase matches DESIGN.md with the exception of the 401 response format. All 6 ESCALATE fixes are implemented and the core ones (TS-31, TS-32, TS-34, TS-35, TS-37) are fully correct.

## Context for Next Step

The review found 2 Important findings and 3 Useful (advisory) findings:
1. **Important**: `$TRANSCRIPT` heredoc interpolation -- same injection class as TS-33 but unfixed
2. **Important**: 401 response is HTML not JSON due to missing error handler
3. **Useful**: README still references deleted legacy scripts (known out-of-scope)
4. **Useful**: uninstall.sh SCRIPTS array still lists deleted scripts (known out-of-scope)
5. **Useful**: settings.conf sourced as shell code in apply-config (accepted convention)

The triage step should decide whether findings #1 and #2 warrant another fix cycle or can be deferred. Finding #1 is the same class as a fix that was just applied (TS-33), making it a natural candidate for immediate follow-up. Finding #2 is a design compliance issue that affects API consumers.

## Pipeline State

- **Phase**: Fix cycle 5 review (post-execute, pre-triage)
- **Mode**: Standard (not yolo)
- **Test count**: 370 passing
- **Commits reviewed**: 4449f52, 8d2ed9d, 0204d5e, bf95bd9, b21805a, c016cf0, f9ef2f7
