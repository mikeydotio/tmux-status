# Triage Report

## Summary
- Total findings: 15 (11 review + 4 validation)
- FIX: 7
- ESCALATE: 3
- No Action Required: 5
- Yolo mode: false
- Fix cycle: 0 / 3

## FIX Items

### FIX-1: pyproject.toml Uses Non-Standard Build Backend — FIX
- **Source**: REVIEW-REPORT #1
- **Severity**: Critical
- **Chosen Solution**: Option 1 — Change to `build-backend = "setuptools.build_meta"`
- **Rationale**: Single correct answer. `setuptools.backends._legacy:_Backend` does not exist in standard setuptools. One-line fix, zero ambiguity. Installation is completely broken without this.
- **Files**: `server/pyproject.toml`

### FIX-2: launchd Plist Uses Tilde in ProgramArguments — FIX
- **Source**: REVIEW-REPORT #2
- **Severity**: Critical
- **Chosen Solution**: Option 1 — `install.sh` sed substitution to replace `~` with `$HOME` before copying the plist
- **Rationale**: launchd does not expand `~`. The DESIGN.md Risks section explicitly anticipated this with the mitigation "Use absolute path with `$HOME` substitution during install." Template plist stays generic; installed version gets absolute paths.
- **Files**: `install.sh` (do NOT modify the template plist or its tests)

### FIX-3: Renderer Ignores Non-"ok"/Non-"error" Server Statuses — FIX
- **Source**: REVIEW-REPORT #3
- **Severity**: Important
- **Chosen Solution**: Option 1 — Add `else` clause setting `five_hour_pct = "X"` and `seven_day_pct = "X"` for any non-"ok" status
- **Rationale**: 3-line change. The design specifies "X" error signaling for all error statuses. Currently "expired", "blocked", "rate_limited" etc. fall through to 0% instead of X%. The bash color logic already handles these statuses correctly; only the Python data extraction is missing the else branch.
- **Files**: `scripts/tmux-claude-status` (Python block, lines ~186-201)

### FIX-4: Dockerfile Default Bind Address 127.0.0.1 — FIX
- **Source**: REVIEW-REPORT #4
- **Severity**: Important
- **Chosen Solution**: Option 1 — Add `CMD ["--host", "0.0.0.0"]` to the Dockerfile after ENTRYPOINT
- **Rationale**: Standard Docker pattern. ENTRYPOINT provides the executable, CMD provides default args. Bare binary still defaults to 127.0.0.1 (safe), Docker default becomes 0.0.0.0 (necessary for port mapping). One-line addition.
- **Files**: `server/Dockerfile`, possibly `server/tests/test_deploy.py` (add CMD test)

### FIX-5: install.sh Source Line Hardcodes ~/projects/tmux-status Path — FIX
- **Source**: REVIEW-REPORT #11
- **Severity**: Important (upgraded from Useful — custom TMUX_STATUS_DIR silently breaks)
- **Chosen Solution**: Option 1 — Use `$INSTALL_DIR` variable instead of hardcoded path in the heredoc
- **Rationale**: The `INSTALL_DIR` variable already exists and is set correctly. The heredoc uses single-quoted delimiter `'TMUXLINE'` which prevents variable expansion. Change to unquoted `TMUXLINE` and use `$INSTALL_DIR/overlay/status.conf`.
- **Files**: `install.sh` (lines ~156-161)

### FIX-6: warn_if_exposed Only Checks "127.0.0.1" — FIX
- **Source**: REVIEW-REPORT #7
- **Severity**: Useful
- **Chosen Solution**: Option 1 — Expand safe-address set to include `"localhost"` and `"::1"`
- **Rationale**: 1-line condition change. Reduces false-positive warnings for common loopback addresses. No behavior change for the common `127.0.0.1` case.
- **Files**: `server/tmux_status_server/config.py`, `server/tests/test_config.py`

### FIX-7: Stale Org UUID Cache After Auth Errors — FIX
- **Source**: REVIEW-REPORT #5
- **Severity**: Important
- **Chosen Solution**: Option 1 — Reset `_org_uuid = None` when 401/403 received from usage endpoint
- **Rationale**: Minimal self-healing fix. If the session key expires or changes, the cached org UUID must be cleared to force re-discovery. 2-line change in a single file. Does NOT refactor the global into an instance variable (that's ESCALATE-3).
- **Files**: `server/tmux_status_server/scraper.py`, `server/tests/test_scraper.py`

## ESCALATE Items

### ESCALATE-1: QUOTA_API_KEY Stored in Plaintext in settings.conf — ESCALATE
- **Source**: REVIEW-REPORT #6
- **Severity**: Important
- **Story**: TS-11
- **Description**: The `QUOTA_API_KEY` setting stores the API key as plaintext in `settings.conf`, inconsistent with the server-side `--api-key-file` approach. The API key only protects access to quota data, not upstream credentials.
- **Options**:
  1. **Add QUOTA_API_KEY_FILE** — Mirrors server approach. Pros: consistent security model. Cons: adds config complexity.
  2. **Document chmod 600** — Add permissions check in renderer. Pros: simple. Cons: plaintext key remains.
  3. **Accept as-is** — Comment in settings.example.conf. Pros: no code change. Cons: inconsistent posture.
- **Recommendation**: Option 3. The API key protects local quota data, not upstream credentials. The session key (security-critical) is already file-based with permission checking.
- **Rationale**: Multiple valid solutions with different trade-offs. Changes user-facing configuration surface. Security design decision not explicitly covered in DESIGN.md for client side.

### ESCALATE-2: __main__.py Unused Imports — ESCALATE
- **Source**: REVIEW-REPORT #8
- **Severity**: Useful
- **Story**: TS-12
- **Description**: `__main__.py` imports `parse_args` and `warn_if_exposed` but never calls them. Tests explicitly check for these imports (test_package.py:78-106, test_server.py:308-315). Removing the imports requires deciding what the tests should verify instead.
- **Options**:
  1. **Remove imports, update tests** — Clean code, tests verify actual behavior. Touches 3 files.
  2. **Keep as-is** — Imports are harmless, tests document the contract. No change.
- **Recommendation**: Option 1, but needs careful review of which tests to update vs remove.
- **Rationale**: Requires judgment about test design philosophy. The tests were recently added during validation.

### ESCALATE-3: Scraper Module-Level _org_uuid Global State — ESCALATE
- **Source**: REVIEW-REPORT #9
- **Severity**: Useful
- **Story**: TS-13
- **Description**: Module-level `_org_uuid` global requires tests to manually reset in setUp(). The operational bug (stale cache) is addressed by FIX-7. This is about the architectural question of refactoring into instance state.
- **Options**:
  1. **Refactor into instance attribute** — Cleaner architecture. Touches scraper.py, server.py, and multiple test files.
  2. **Keep as-is** — Tech debt acknowledged. Tests handle it correctly today.
- **Recommendation**: Option 2. FIX-7 addresses the operational concern. Full refactor is a future improvement.
- **Rationale**: Moderate refactor crossing module boundaries. Multiple approaches with different scope.

## No Action Required

| # | Finding | Source | Severity | Reason |
|---|---------|--------|----------|--------|
| 1 | No graceful Bottle shutdown | REVIEW #10 | Useful | Known limitation of WSGIRef. Systemd/launchd handle SIGKILL after timeout. Over-engineering for a status bar utility. |
| 2 | Empty API key file disables auth | VALIDATE #1 | Useful | Consistent behavior (empty = no key = no auth). Test documents it. Degenerate edge case. |
| 3 | No API key file permission enforcement | VALIDATE #2 | Useful | API key protects local endpoint, not upstream credentials. Session key IS permission-checked. Asymmetry noted, risk low. |
| 4 | Client renderer not unit-tested | VALIDATE #3 | Useful | Explicitly out of scope per PLAN.md. Bash/embedded-Python hybrid not amenable to pytest. Silent-failure design limits blast radius. |
| 5 | Malformed usage returns ok with None | VALIDATE #4 | Useful | Upstream always sends valid schema. Renderer handles non-numeric values gracefully via 2>/dev/null. Defense-in-depth for unlikely scenario. |

## Consolidations

- **R5 and R9 share a root cause** (module-level `_org_uuid`). R5 is the operational bug (FIX-7: clear on 401/403). R9 is the architectural concern (ESCALATE-3: refactor into instance state). Addressed separately because FIX-7 is a targeted 2-line fix while ESCALATE-3 is a moderate refactor.
- **R6, V1, V2 share a theme** (API key handling). R6 escalated for user decision on security posture. V1 and V2 are informational with low practical risk.

## Risk Assessment

**FIX items are all low-risk, localized changes:**
- FIX-1, FIX-2: **Blockers** — installation fails and macOS daemon won't start without these
- FIX-3: **Functional gap** — misleading 0% instead of X% for error states
- FIX-4: **Docker usability blocker** — container service unreachable
- FIX-5: **Correctness** — custom install directories silently break
- FIX-6, FIX-7: **Quality improvements** — false positive reduction and self-healing

**ESCALATE items are all non-blocking:**
- None block a functional release. Can all be deferred without user-facing impact.
