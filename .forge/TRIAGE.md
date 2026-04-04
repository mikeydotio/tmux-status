# Triage Report

## Summary
- Total findings: 9 (deduplicated across REVIEW-REPORT and VALIDATE-REPORT)
- FIX: 4
- ESCALATE: 2 (new) + 3 (prior: TS-11, TS-12, TS-13)
- DEFER: 3 (advisory, no stories)
- Yolo mode: false
- Fix cycle: 2 / 3 (max)

## FIX Items

### 1. API Key Auth Bypass + Auth Tests — FIX
- **Source**: REVIEW-REPORT findings 1 & 2
- **Severity**: Critical
- **Chosen Solution**: Replace `return json.dumps(...)` with `abort(401, json.dumps(...))` in `check_auth` hook (server.py:82-84). Add integration tests using real HTTP requests to verify auth rejection prevents data leakage.
- **Rationale**: One-line production fix. `abort()` is already imported at line 68. The existing unit tests remain valid but insufficient alone — integration tests must prove the fix works end-to-end. No design decision needed; DESIGN.md already specifies this behavior.
- **Acceptance**: (1) `/quota` without valid API key returns 401 AND body does NOT contain quota data. (2) At least 3 integration tests exercise full Bottle request pipeline. (3) All existing 292 tests pass.

### 2. Renderer Crashes on None Utilization — FIX
- **Source**: REVIEW-REPORT finding 4
- **Severity**: Important
- **Chosen Solution**: Guard with `if fh_util is None or fh_util == "X"` at lines 189 and 193 of `scripts/tmux-claude-status`.
- **Rationale**: Single correct solution. The guard already exists for `"X"` string values; it just needs to also handle `None`. Two-line change. Previous triage incorrectly dismissed this as handled by `2>/dev/null` — the Python code crashes before bash ever runs.
- **Acceptance**: When scraper returns `{"status": "ok", "five_hour": {"utilization": null}}`, renderer displays "X%" instead of crashing.

### 3. Empty API Key File Auth Bypass — FIX
- **Source**: REVIEW-REPORT finding 5, VALIDATE-REPORT FINDING-1
- **Severity**: Critical
- **Chosen Solution**: In `_load_api_key()`, return `None` when stripped key is empty. Log WARNING about disabled auth.
- **Rationale**: Both review and validation converge on the same fix. Empty key file should mean "no key configured" (auth disabled), not "auth enabled with empty key that matches empty header." Two-line change in `_load_api_key()`.
- **Acceptance**: (1) Empty key file causes `_load_api_key()` to return `None`. (2) Auth is disabled when key is None. (3) WARNING logged. (4) Security tests updated.

## ESCALATE Items

### 4. SIGTERM Does Not Shut Down HTTP Server — ESCALATE
- **Source**: REVIEW-REPORT finding 3
- **Severity**: Important
- **Story**: TS-22
- **Description**: Custom `_handle_sigterm` replaces Python's default SIGTERM handler (which raises SystemExit). The custom handler sets flags but `serve_forever()` doesn't check them. Server is unkillable via `kill`. Installing the custom handler is actually WORSE than no handler.
- **Options**:
  1. **raise SystemExit(0) in handler** — Most Pythonic. serve_forever() propagates it. Poll thread is daemon. Pro: Lets Python handle cleanup. Con: Depends on Bottle/WSGIRef internals.
  2. **os._exit(0) after setting shutdown events** — Guaranteed exit. Pro: No framework dependency. Con: Skips all cleanup.
  3. **Keep current behavior, document limitation** — Systemd/launchd handle SIGKILL after timeout. Pro: No code change. Con: 30s+ delayed shutdown.
- **Recommendation**: Option 1 (raise SystemExit(0))
- **Rationale**: Multiple valid solutions with different trade-offs. Previous triage dismissed this incorrectly. The custom handler makes the situation worse than Python's default, which is a real operational defect. User should decide the shutdown strategy.

### 5. Client _maybe_fetch_quota Embedded in Shell Script — ESCALATE
- **Source**: VALIDATE-REPORT FINDING-2
- **Severity**: Important
- **Story**: TS-23
- **Description**: 26-line Python function embedded in bash/python polyglot script. Cannot be imported or tested directly. Validation tests re-implement the function. Drift risk between test and real code.
- **Options**:
  1. **Extract to `scripts/tmux_status_client.py`** — Importable by both polyglot and tests. Pro: Direct testing, no drift. Con: Changes deployment model and script architecture.
  2. **Add source-hash verification in tests** — No structural change. Pro: Catches drift. Con: Fragile, breaks on whitespace.
  3. **Accept re-implementation approach** — Function is stable and small. Pro: No change needed. Con: Drift risk if function evolves.
- **Recommendation**: Option 3 for now. Extract later if function grows.
- **Rationale**: Architectural decision that changes the project's script structure. User should decide whether the testing purity is worth the structural change.

## DEFER Items (No Stories)

### 6. pip install stderr suppressed — DEFER
- **Source**: REVIEW-REPORT finding 6 (Useful)
- **Rationale**: Install script already detects pip failure and prints an error. Users can run pip manually for details. Low impact.

### 7. Private API coupling: _error_bridge import — DEFER
- **Source**: REVIEW-REPORT finding 7 (Useful)
- **Rationale**: Naming convention issue within the same package. Cosmetic, zero user impact.

### 8. API key file not permission-checked — DEFER
- **Source**: REVIEW-REPORT finding 8 (Useful)
- **Rationale**: API key protects quota percentages (not credentials). Session key IS checked (higher threat level). Asymmetry is intentional.

## Prior ESCALATE Stories (Carried Forward)

| Story | Finding | Status |
|-------|---------|--------|
| TS-11 | QUOTA_API_KEY stored in plaintext in settings.conf | todo |
| TS-12 | __main__.py unused imports (parse_args, warn_if_exposed) | todo |
| TS-13 | Scraper module-level _org_uuid global state | todo |
