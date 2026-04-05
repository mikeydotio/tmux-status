# Review Report

## Summary

Fix cycle 5 successfully addressed all 6 ESCALATE items: the `session_key_expired` status code mismatch is fixed, shell injection via pidfile interpolation is eliminated, the Dockerfile runs as a non-root user, context hook uses atomic writes, legacy quota scripts are removed, and server interval validation rejects values below 30 seconds. However, the shell injection fix (TS-33) was applied narrowly to `$pidfile` only -- the same class of vulnerability persists via `$TRANSCRIPT` interpolation in the same heredoc on line 49. Additionally, the 401 auth error response violates the API's JSON contract because there is no Bottle error handler registered for that status code.

## Findings

### 1. Shell interpolation of $TRANSCRIPT in Python heredoc
- **Severity**: Important
- **Description**: TS-33 fixed shell injection via `$pidfile` by switching to `sys.argv`, but the same unquoted heredoc (`<< PYEOF` at line 46) still interpolates `$TRANSCRIPT` directly into a Python string on line 49: `transcript = "$TRANSCRIPT"`. If a `.jsonl` filename contains characters meaningful to Python (quotes, backslashes), this breaks or produces unexpected behavior. While Claude Code names JSONL files with UUIDs (making practical exploitation unlikely), this is the same vulnerability class that TS-33 was specifically created to eliminate.
- **Location**: `scripts/tmux-claude-status:49`
- **Option 1 (Recommended)**: Pass `$TRANSCRIPT` as a second positional argument to the python3 heredoc, read it via `sys.argv[2]` inside the Python block, and quote the heredoc delimiter (`<< 'PYEOF'`) to prevent all shell expansion. This would require also passing `$TRANSCRIPT` as an explicit argument to the `python3` invocation. -- Pros: Eliminates the entire class of injection for this heredoc. Cons: Requires restructuring how the heredoc receives its inputs (all shell vars would need to be passed as arguments or environment variables).
- **Option 2**: Pass only `$TRANSCRIPT` via an environment variable (`TRANSCRIPT="$TRANSCRIPT" python3 << PYEOF`) and read it with `os.environ["TRANSCRIPT"]` inside Python, leaving the heredoc unquoted for other variables that don't come from filesystem paths. -- Pros: Minimal change, targeted fix. Cons: Still leaves the heredoc unquoted, so other shell variables are still interpolated (though they come from controlled sources).

### 2. 401 response is not JSON (missing Bottle error handler)
- **Severity**: Important
- **Description**: The `check_auth` before_request hook calls `abort(401, json.dumps({"error": "invalid_or_missing_api_key"}))`. However, Bottle's `abort()` raises an `HTTPError` that gets rendered by the default error handler as `text/html`. The server registers custom `@app.error(404)` and `@app.error(500)` handlers that return JSON, but no `@app.error(401)` handler exists. This means the API contract in DESIGN.md ("Auth failure (401): `{"error": "invalid_or_missing_api_key"}`" with "All responses are Content-Type: application/json") is violated -- the actual response will be an HTML error page wrapping the JSON string.
- **Location**: `server/tmux_status_server/server.py:87` (abort call) and `server/tmux_status_server/server.py:119-127` (missing 401 handler)
- **Option 1 (Recommended)**: Add an `@app.error(401)` handler that sets `response.content_type = "application/json"` and returns `json.dumps({"error": "invalid_or_missing_api_key"})`. -- Pros: Matches DESIGN.md spec, consistent with 404/500 handlers. Cons: The abort body is ignored by custom error handlers, so the JSON body needs to be hardcoded in the handler.
- **Option 2**: Instead of `abort(401, ...)`, set `response.status = 401` and `response.content_type = "application/json"` directly in `check_auth`, then return the JSON body. This requires restructuring `check_auth` to use Bottle's response object rather than abort. -- Pros: More explicit control over the response. Cons: `before_request` hooks in Bottle can't easily short-circuit the request; abort is the standard way to halt processing.

### 3. README references deleted legacy scripts
- **Severity**: Useful
- **Description**: TS-35 removed `tmux-status-quota-fetch` and `tmux-status-quota-poll` from the repo and `install.sh`, but `README.md` lines 250-259 still instruct users to run `tmux-status-quota-poll` and `tmux-status-quota-fetch`. Users following the README will encounter "command not found" errors. The PLAN.md explicitly listed README updates as out of scope for fix cycle 5, so this is expected -- but worth tracking.
- **Location**: `README.md:250-259`
- **Option 1 (Recommended)**: Update the README quota section to reference the new server-based architecture (`tmux-status-server`, `curl http://127.0.0.1:7850/quota`). -- Pros: Documentation matches reality. Cons: Slightly more work.
- **Option 2**: Add a deprecation notice at the top of the quota section pointing users to the server. -- Pros: Minimal edit. Cons: Confusing to have deprecated instructions still present.

### 4. uninstall.sh still lists legacy scripts in SCRIPTS array
- **Severity**: Useful
- **Description**: `uninstall.sh:20` still includes `tmux-status-quota-fetch` and `tmux-status-quota-poll` in its `SCRIPTS` array. While this is harmless (the uninstaller gracefully handles missing symlinks), it creates dead entries that will never match. The fix cycle 5 scope note acknowledges this: "Updating uninstall.sh to stop removing legacy scripts (it handles missing files gracefully)" was explicitly out of scope.
- **Location**: `uninstall.sh:20`
- **Option 1 (Recommended)**: Remove the two legacy script names from the SCRIPTS array. -- Pros: Clean code. Cons: Functionally irrelevant change.
- **Option 2**: Leave as-is; the uninstaller correctly handles the case where these symlinks don't exist (the `[ -L "$dst" ]` check skips non-existent paths). -- Pros: Zero risk. Cons: Dead references remain.

### 5. settings.conf sourced as shell code in apply-config
- **Severity**: Useful
- **Description**: `tmux-status-apply-config:17` uses `. "$CONFIG_FILE"` to source `settings.conf` directly as shell code. If a user puts arbitrary shell commands in their settings file (e.g., `CLOCK_24H=true; rm -rf /`), they will be executed. This is a common pattern for user config files and the user owns the file, so it's not a security vulnerability per se -- but it contrasts with the Python-based settings parser in `tmux-claude-status` which safely parses key=value pairs. The only sanitization is the `TOP_BANNER_COLOR` regex check on line 20.
- **Location**: `scripts/tmux-status-apply-config:17`
- **Option 1**: Replace the shell source with a key=value parser (a `while read` loop with `case` dispatch), matching the approach used in other scripts. -- Pros: Eliminates code execution from config. Cons: More code, changes a working pattern.
- **Option 2 (Recommended)**: Accept as-is. The config file lives in a user-owned directory (`~/.config/tmux-status/`), and sourcing user config is a standard shell convention (e.g., `.bashrc`, `.profile`). Document the trust assumption. -- Pros: No change needed. Cons: Config is technically executable.

## Design Alignment

**ALIGNED** -- The implemented architecture matches DESIGN.md closely:

- The server is the canonical owner of scraping logic (scraper.py replaces the old standalone scripts).
- The renderer fetches from `QUOTA_SOURCE` URL, writes to disk cache as fallback, uses `urllib.request` with 3s timeout.
- `/quota` and `/health` endpoints follow the specified JSON response formats.
- API key auth uses `hmac.compare_digest()` in a `before_request` hook; `/health` is exempt.
- Error signaling uses `"X"` utilization values as designed.
- Signal handling (SIGTERM/SIGINT/SIGUSR1) matches spec.
- Atomic writes use temp-file + `os.replace()` as specified.
- Default bind is `127.0.0.1` with startup warning on non-localhost without auth.

**Minor drift**: The 401 response format doesn't match the DESIGN.md spec (Finding #2 above). The spec says all responses are `Content-Type: application/json`, but the actual 401 will be HTML due to the missing error handler.

## Story Hygiene

| Story | Fix Verified | Notes |
|-------|-------------|-------|
| TS-31 | YES | Line 298 case pattern now includes `session_key_expired` instead of bare `expired`. The full pattern covers `session_key_expired\|blocked\|error\|rate_limited\|key_expired`. |
| TS-32 | YES | `server/Dockerfile` creates `appuser` with `useradd -r -s /usr/sbin/nologin` and `USER appuser` appears after `RUN pip install` and before `ENTRYPOINT`. Test coverage in `test_deploy.py::TestDockerfileUser`. |
| TS-33 | PARTIAL | The `$pidfile` interpolation at lines 22 and 27 was correctly fixed to use `sys.argv[1]`. However, the `$TRANSCRIPT` variable interpolation on line 49 of the same heredoc was not addressed -- this is the same vulnerability class. |
| TS-34 | YES | `scripts/tmux-status-context-hook.js` writes to `tmpPath = bridgePath + '.tmp'` then calls `fs.renameSync(tmpPath, bridgePath)`. Clean atomic write pattern. |
| TS-35 | YES | `scripts/tmux-status-quota-fetch` and `scripts/tmux-status-quota-poll` are deleted. `install.sh` SCRIPTS array contains only the 5 remaining scripts. |
| TS-37 | YES | `server/tmux_status_server/config.py:71` validates `args.interval < 30` with `parser.error()`. Test coverage in `test_config.py::TestIntervalLowerBound` with boundary tests (29 rejected, 30 accepted, 1 rejected, 300 accepted). |

## Strengths

- **Atomic writes are consistent**: Both the Python renderer (line 165-168 in tmux-claude-status) and the Node.js context hook use the tmp+rename pattern correctly. The convention is well established.
- **Error signaling is clean**: The `"X"` utilization pattern flows cleanly from server through cache to renderer. The `bar_char` function handles non-numeric input gracefully (line 270-273).
- **Test coverage is thorough**: 370 tests cover config parsing, scraper behavior, server endpoints, deployment files, and edge cases. The interval lower bound has proper boundary testing.
- **The pidfile injection fix is well done**: Using `sys.argv[1]` is the correct approach, and both occurrences (lines 22 and 27) were updated symmetrically.
- **Credential protection is solid**: Session key file permissions are checked (0o077 mask), credentials never appear in API responses, error messages use generic codes, and the API key comparison is timing-safe.
- **Silent failure discipline is maintained**: The renderer produces zero error output -- on any failure it either exits 0 or falls through to stale cache. This is critical for a tmux status bar where error output would corrupt the display.
