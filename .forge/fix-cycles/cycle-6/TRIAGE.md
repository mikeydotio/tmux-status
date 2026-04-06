# Triage Report

## Summary
- Total findings: 8 (5 review + 3 validate)
- Resolved: 3 (V1 tests written, V2 tests added, V3 third-party not actionable)
- FIX: 0 (max fix cycles exceeded — 2 items promoted to ESCALATE)
- ESCALATE: 2 (TS-39, TS-40)
- Deferred (advisory): 3
- Yolo mode: false
- Fix cycle: 5 / max 3 (exceeded)

## FIX Items

None — max fix cycles exceeded. Two findings that would have been FIX were promoted to ESCALATE.

## ESCALATE Items

### $TRANSCRIPT shell interpolation in Python heredoc — ESCALATE
- **Source**: REVIEW-REPORT Finding 1
- **Severity**: Important
- **Story**: TS-39
- **Description**: TS-33 fixed shell injection via `$pidfile` by switching to `sys.argv`, but the same unquoted heredoc (`<< PYEOF` at line 46) still interpolates `$TRANSCRIPT` directly into a Python string on line 49 of `scripts/tmux-claude-status`. While Claude Code names JSONL files with UUIDs (making practical exploitation unlikely), this is the same vulnerability class that TS-33 was specifically created to eliminate.
- **Options**:
  1. **Quote heredoc + sys.argv for all vars** — Change `<< PYEOF` to `<< 'PYEOF'`, pass `$TRANSCRIPT` as `sys.argv[2]`, convert all shell var references to positional args. Pros: Eliminates entire injection class. Cons: Larger change, must audit all `$VAR` references in heredoc, touches critical rendering path.
  2. **Environment variable for $TRANSCRIPT only** — `TRANSCRIPT="$TRANSCRIPT" python3 << PYEOF` and read via `os.environ["TRANSCRIPT"]`. Pros: Minimal targeted change, low regression risk. Cons: Leaves heredoc unquoted for other variables.
  3. **Defer as accepted risk** — Document that Claude Code uses UUID filenames, no code change. Pros: Zero regression risk. Cons: Inconsistency with TS-33 fix remains.
- **Recommendation**: Option 2 for pragmatic fix, or Option 3 to defer. QA notes moderate regression risk on critical rendering path — regression would be worse than the vulnerability.
- **Rationale**: Promoted from FIX due to max_fix_cycles exceeded. Theoretical risk only — Claude Code generates UUID-based filenames. The fix touches a critical rendering path where silent failure would break the primary status bar feature.

### 401 response is HTML not JSON — ESCALATE
- **Source**: REVIEW-REPORT Finding 2
- **Severity**: Important
- **Story**: TS-40
- **Description**: The `check_auth` before_request hook calls `abort(401, ...)` but Bottle's default error handler renders it as HTML. The server has `@app.error(404)` and `@app.error(500)` handlers but no `@app.error(401)`. This violates the DESIGN.md spec that all responses are `Content-Type: application/json`.
- **Options**:
  1. **(Recommended) Add @app.error(401) handler** — 3-line change matching existing 404/500 pattern. Pros: Matches DESIGN.md spec, consistent, low regression risk. Cons: abort body is ignored by custom handlers so JSON is hardcoded.
  2. **Restructure check_auth** — Use response object directly instead of abort. Pros: More explicit. Cons: before_request hooks can't easily short-circuit in Bottle.
  3. **Defer** — Status code 401 is correct, only body format is wrong. Pros: Zero risk. Cons: API contract violation remains.
- **Recommendation**: Option 1 — straightforward fix matching existing pattern.
- **Rationale**: Promoted from FIX due to max_fix_cycles exceeded. Low practical impact — the renderer checks status codes, not response bodies. Only affects direct API consumers parsing 401 bodies.

## Deferred Items (Advisory)

### README references deleted legacy scripts — DEFER
- **Source**: REVIEW-REPORT Finding 3
- **Severity**: Useful
- **Rationale**: Explicitly scoped out of fix cycle 5. Documentation-only issue. Users following README will hit "command not found" but `install.sh` correctly omits legacy scripts.

### uninstall.sh dead entries in SCRIPTS array — DEFER
- **Source**: REVIEW-REPORT Finding 4
- **Severity**: Useful
- **Rationale**: Explicitly scoped out of fix cycle 5. Functionally harmless — the `[ -L "$dst" ]` check gracefully skips non-existent symlinks. Zero user impact.

### settings.conf sourced as shell code — DEFER
- **Source**: REVIEW-REPORT Finding 5
- **Severity**: Useful
- **Rationale**: Accepted shell convention. User-owned file in `~/.config/tmux-status/`. Standard practice (like `.bashrc`, `.profile`). The reviewer themselves recommended accepting this.

## Resolved Findings (No Action)

| Finding | Source | Resolution |
|---------|--------|------------|
| Fix cycle 5 fixes had no test coverage | VALIDATE Finding 1 | Resolved — 36 tests written in `test_validate_cycle5.py` |
| No test for negative interval values | VALIDATE Finding 2 | Resolved — boundary tests added |
| webob deprecation warning | VALIDATE Finding 3 | Not actionable — third-party library, awaiting upstream fix |

## Team Deliberation Notes

**Triager**: Both Important findings warrant ESCALATE stories. Finding 1 is an incomplete remediation of TS-33's scope. Finding 2 is a clear spec violation.

**QA Engineer**: Finding 1's fix carries moderate regression risk on a critical rendering path — the regression (broken status bar) would be worse than the vulnerability (theoretical injection via UUID filenames). Finding 2 is a genuine coverage gap (content-type not asserted in tests). Neither justifies breaking the cycle cap.

**Consensus**: Both promoted to ESCALATE per max_fix_cycles rule. Neither is a blocker. The codebase is in a shippable state at 406 passing tests with all cycle-5 stories verified.
