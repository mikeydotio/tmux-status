# Triage Report

## Summary
- Total findings: 9 (deduplicated across REVIEW-REPORT.md and VALIDATE-REPORT.md)
- FIX: 0 (all promoted to ESCALATE — max fix cycles reached)
- ESCALATE: 7
- ACCEPTED: 2 (no action needed)
- Yolo mode: false
- Fix cycle: 4 / max 3 — **max fix cycles reached, all FIX items promoted to ESCALATE**

## Deliberation Notes

All 7 actionable findings had a natural FIX disposition — each has a single obvious solution with low risk. However, the pipeline has already completed 4 fix cycles (cycle-0 through cycle-3), exceeding the configured `max_fix_cycles: 3`. Per protocol, all remaining FIX items are promoted to ESCALATE to prevent infinite fix loops. The user must review and decide which items to address.

## ESCALATE Items

### Status Code Mismatch — ESCALATE (promoted from FIX)
- **Story**: TS-31
- **Source**: REVIEW-REPORT + VALIDATE-REPORT (confirmed by WSGI integration test)
- **Severity**: Critical
- **Description**: Server scraper (`scraper.py:117`) maps HTTP 401 to `"session_key_expired"`, but renderer (`tmux-claude-status:298`) checks for `"expired"`. Expired session keys don't trigger the red color indicator — a functional regression.
- **Options**:
  1. **Update renderer case pattern** — Add `session_key_expired` alongside `expired` in the case pattern. Backward-compatible, no server change. (Recommended)
  2. **Change server status_map** — Use `"expired"` instead of `"session_key_expired"` for HTTP 401. Matches DESIGN.md but requires updating all server tests.
- **Recommendation**: Option 1
- **Rationale**: Natural FIX (single obvious solution), promoted due to max fix cycles

### Dockerfile Runs as Root — ESCALATE (promoted from FIX)
- **Story**: TS-32
- **Source**: REVIEW-REPORT
- **Severity**: Critical
- **Description**: `server/Dockerfile` has no `USER` directive. Process runs as root with default `0.0.0.0` bind, compounding exposure.
- **Options**:
  1. **Add non-root user in Dockerfile** — `RUN useradd -r -s /usr/sbin/nologin appuser` then `USER appuser`. Secure by default. (Recommended)
  2. **Document --user flag** — Rely on operator to pass `--user` at runtime. Less secure by default.
- **Recommendation**: Option 1
- **Rationale**: Natural FIX (standard security practice), promoted due to max fix cycles

### Shell Injection via Filename in Polyglot Script — ESCALATE (promoted from FIX)
- **Story**: TS-33
- **Source**: REVIEW-REPORT
- **Severity**: Important
- **Description**: `$pidfile` interpolated into Python string literal at `tmux-claude-status:22`. Exploitation requires attacker write access to `~/.claude/sessions/` (low practical risk), but poor code quality.
- **Options**:
  1. **Pass filename via sys.argv** — `python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['pid'])" "$pidfile"`. Eliminates injection entirely. (Recommended)
  2. **Use jq** — `pid=$(jq -r '.pid' "$pidfile")`. Simpler but adds dependency.
- **Recommendation**: Option 1
- **Rationale**: Natural FIX (single obvious solution), promoted due to max fix cycles

### Context Hook Non-Atomic writeFileSync — ESCALATE (promoted from FIX)
- **Story**: TS-34
- **Source**: REVIEW-REPORT
- **Severity**: Important
- **Description**: `tmux-status-context-hook.js:55` uses `writeFileSync()` directly instead of temp+rename. Violates the project's "atomic writes everywhere" convention.
- **Options**:
  1. **Add temp+rename** — Write to `.tmp` then `renameSync`. 2 extra lines. (Recommended)
  2. **Accept as exception** — Document the inconsistency. Payload <100 bytes, partial reads unlikely.
- **Recommendation**: Option 1
- **Rationale**: Natural FIX (trivial, consistency), promoted due to max fix cycles

### Legacy Scripts Still Shipped — ESCALATE (promoted from FIX)
- **Story**: TS-35
- **Source**: REVIEW-REPORT
- **Severity**: Important
- **Description**: Deprecated `tmux-status-quota-fetch` and `tmux-status-quota-poll` still symlinked by `install.sh:22` despite DESIGN.md marking them deprecated. Confusing for users.
- **Options**:
  1. **Remove from SCRIPTS array** — Stop symlinking deprecated scripts. Keep files in repo. Uninstaller handles cleanup. (Recommended)
  2. **Add deprecation warnings** — Print one-time warning on execution. More maintenance.
- **Recommendation**: Option 1
- **Rationale**: Natural FIX (clean break), promoted due to max fix cycles

### Old Fetch Script Exposes Raw Exception Text — ESCALATE (promoted from FIX)
- **Story**: TS-36
- **Source**: REVIEW-REPORT
- **Severity**: Important
- **Description**: Deprecated `tmux-status-quota-fetch:278` writes `str(e)` into bridge file error field. Can expose file paths, tracebacks. New server uses machine-readable codes.
- **Options**:
  1. **Replace str(e) with machine-readable code** — Change to `"error": "fetch_error"`.
  2. **Rely on TS-35** — If deprecated script is removed from install.sh, issue is moot for new installs. (Recommended if TS-35 accepted)
- **Recommendation**: Option 2 (depends on TS-35 decision)
- **Rationale**: Natural FIX, promoted due to max fix cycles. Linked to TS-35.

### No Interval Lower Bound Validation — ESCALATE (promoted from FIX)
- **Story**: TS-37
- **Source**: REVIEW-REPORT + VALIDATE-REPORT
- **Severity**: Useful
- **Description**: `--interval` accepts 0 and negative values. Interval 0 causes continuous scraping loop. Old `tmux-status-quota-poll` had `MIN_INTERVAL = 30`.
- **Options**:
  1. **Validate in parse_args()** — `if args.interval < 30: parser.error(...)`. Clear error message. (Recommended)
  2. **Clamp in QuotaServer.__init__** — `max(30, interval)`. Silent behavior change.
- **Recommendation**: Option 1
- **Rationale**: Natural FIX (simple validation), promoted due to max fix cycles

## Accepted Items (No Action)

### Duplicate Scraping Logic — ACCEPTED
- **Source**: REVIEW-REPORT
- **Severity**: Useful
- **Description**: Request headers, org discovery, and usage extraction duplicated between `scraper.py` and deprecated `tmux-status-quota-fetch`. DESIGN.md designates the server as canonical.
- **Rationale**: Accepted as transitional state. Deprecated scripts will be removed in future cleanup (related to TS-35). No immediate action needed.

### QUOTA_API_KEY Plaintext — PREVIOUSLY ACCEPTED (TS-11)
- **Source**: REVIEW-REPORT
- **Severity**: Useful
- **Description**: API key stored as plaintext in `settings.conf`. Previously escalated and accepted — key only protects quota utilization data, not upstream credentials.
- **Rationale**: Already reviewed and accepted in ESCALATE cycle (TS-11, done). No re-triage needed.
