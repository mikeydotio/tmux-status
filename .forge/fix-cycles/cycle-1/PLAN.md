# Implementation Plan — Fix Cycle 1

Fix cycle 1 of 3. Addresses 7 FIX items from triage. All fixes are independent, localized, and low-risk.

## Task Breakdown

### Wave 1 (all independent — no dependencies)

- [ ] Task 1.1: Fix pyproject.toml build backend (FIX-1, Critical)
  - Change `build-backend` from `"setuptools.backends._legacy:_Backend"` to `"setuptools.build_meta"` in `server/pyproject.toml`
  - Acceptance: `server/pyproject.toml` contains `build-backend = "setuptools.build_meta"` and `pip install server/` succeeds
  - Files: `server/pyproject.toml`

- [ ] Task 1.2: Fix launchd plist tilde expansion (FIX-2, Critical)
  - In `install.sh`, after copying the launchd plist to `$LAUNCHD_PLIST`, run `sed -i '' "s|~|$HOME|g" "$LAUNCHD_PLIST"` to replace `~` with the absolute home path before `launchctl load`
  - Acceptance: The installed plist (after sed) contains absolute paths like `/Users/foo/.local/bin/tmux-status-server` instead of `~/.local/bin/tmux-status-server`. The template plist at `server/deploy/io.mikey.tmux-status-server.plist` is NOT modified. Test `test_deploy.py::test_launchd_plist_*` tests still pass.
  - Files: `install.sh`

- [ ] Task 1.3: Fix renderer status fallthrough (FIX-3, Important)
  - In `scripts/tmux-claude-status`, add an `else` clause after the `elif quota_status == "error"` block to set `five_hour_pct = "X"` and `seven_day_pct = "X"` for any unrecognized status (e.g., "expired", "blocked", "rate_limited", "session_key_expired")
  - Acceptance: When the bridge file has `"status": "session_key_expired"` (or any non-"ok"/non-"error"/non-"none" status), the renderer outputs `QUOTA_5H_PCT='X'` and `QUOTA_7D_PCT='X'` instead of `0`
  - Files: `scripts/tmux-claude-status`

- [ ] Task 1.4: Fix Dockerfile default bind address (FIX-4, Important)
  - Add `CMD ["--host", "0.0.0.0"]` after the `ENTRYPOINT` line in `server/Dockerfile`
  - Acceptance: `server/Dockerfile` has both `ENTRYPOINT ["tmux-status-server"]` and `CMD ["--host", "0.0.0.0"]`. Add a test in `test_deploy.py` verifying the CMD line is present.
  - Files: `server/Dockerfile`, `server/tests/test_deploy.py`

- [ ] Task 1.5: Fix install.sh hardcoded path (FIX-5, Important)
  - In `install.sh`, change the tmux.conf heredoc from single-quoted `'TMUXLINE'` to unquoted `TMUXLINE` and replace the hardcoded `~/projects/tmux-status/overlay/status.conf` with `$INSTALL_DIR/overlay/status.conf`
  - Acceptance: The `source-file` line written to tmux.conf uses the value of `$INSTALL_DIR` (which defaults to `$HOME/projects/tmux-status` but respects `$TMUX_STATUS_DIR`), not a hardcoded path. `grep -F 'INSTALL_DIR' install.sh` matches the heredoc line.
  - Files: `install.sh`

- [ ] Task 1.6: Expand warn_if_exposed safe addresses (FIX-6, Useful)
  - In `server/tmux_status_server/config.py`, change `warn_if_exposed()` to check `args.host not in ("127.0.0.1", "localhost", "::1")` instead of `args.host != "127.0.0.1"`
  - Acceptance: `warn_if_exposed` does NOT log a warning when host is `"localhost"` or `"::1"` (with no api_key_file). It still warns for `"0.0.0.0"`. Update existing tests in `test_config.py` to cover localhost and ::1.
  - Files: `server/tmux_status_server/config.py`, `server/tests/test_config.py`

- [ ] Task 1.7: Reset stale org UUID on auth errors (FIX-7, Important)
  - In `server/tmux_status_server/scraper.py`, within `fetch_quota()`, reset `_org_uuid = None` when the usage endpoint returns 401 or 403 (before returning the error bridge)
  - Acceptance: After a 401/403 from the usage endpoint, `_org_uuid` is `None` so the next `fetch_quota()` call re-discovers the org. Add a test in `test_scraper.py` verifying that `_org_uuid` is reset on 401/403 from the usage endpoint.
  - Files: `server/tmux_status_server/scraper.py`, `server/tests/test_scraper.py`

## Test Strategy

- All server-side fixes (1.1, 1.4, 1.6, 1.7) have existing test suites — add targeted test cases for each fix
- FIX-2 and FIX-5 are install script changes — validate by reading the modified install.sh
- FIX-3 is an embedded Python block in a bash script — validate by code inspection (no pytest infrastructure for this)
- Run `cd server && python -m pytest` after all server-side fixes to confirm no regressions

## Resumption Points

After Wave 1 (all tasks), state is consistent — all fixes applied and tested.

## Risk Register

- **Low**: FIX-2 sed command must handle macOS vs Linux `sed -i` syntax. Use `sed -i ''` for macOS (launchd is macOS-only, so this is correct).
- **Low**: FIX-5 heredoc variable expansion may need escaping for `$HOME` in the source-file path. Use `$INSTALL_DIR` which is already set.
