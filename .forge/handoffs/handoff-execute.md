# Work Handoff

## Session Summary
- **Session**: session-fix1-004
- **Stories completed**: 1 (TS-18)
- **Stories attempted**: 1
- **Status**: Session limit reached (1/1 stories per session)

## What Happened
Fix cycle 1, session 4. Implemented TS-18 (Dockerfile default bind address). Added `CMD ["--host", "0.0.0.0"]` after `ENTRYPOINT ["tmux-status-server"]` in `server/Dockerfile`. Added `TestDockerfileCmd` test class in `test_deploy.py` with 3 tests: cmd_present, cmd_binds_all_interfaces, cmd_after_entrypoint.

Also recovered TS-16 and TS-17 storyhook state — both were committed in prior sessions but storyhook state wasn't synced (TS-16 stuck in verifying, TS-17 stuck in todo).

## Stories Completed This Session
- TS-18: Fix Dockerfile default bind address — added CMD and test class

## Fix Cycle 1 Progress
- TS-15: Done (session 1) — pyproject.toml build backend
- TS-16: Done (session 2, state recovered session 4) — launchd plist tilde expansion
- TS-17: Done (session 3, state recovered session 4) — renderer status fallthrough
- TS-18: Done (this session) — Dockerfile bind address
- TS-19: Todo — install.sh hardcoded path
- TS-20: Todo — warn_if_exposed safe addresses
- TS-21: Todo — stale org UUID on auth errors

## Current Blockers
None.

## Working Context

### Patterns Established
- Config module uses module-level constants for defaults (DEFAULT_HOST, DEFAULT_PORT, etc.)
- Scraper module uses module-level `_org_uuid` cache variable
- Tilde expansion via `os.path.expanduser()` applied post-parse, not in defaults
- Warning function is a separate callable (`warn_if_exposed(args)`)
- Tests use `sys.path.insert` to import from `server/tmux_status_server/`
- Test files use unittest-style classes under pytest
- Shell scripts use `2>/dev/null || true` for silent failure on optional commands
- OS detection uses `uname -s` checking for "Linux" and "Darwin"
- pip3 used with fallback to pip; pip3 uninstall uses `-y` flag
- pyproject.toml uses `[tool.setuptools.packages.find]` with explicit include
- macOS sed uses `sed -i ''` (BSD syntax with explicit empty backup extension)
- launchd plist sed uses pipe `|` delimiter to avoid conflicts with `/` in paths
- Embedded Python in tmux-claude-status uses `if/elif/else` chain for quota_status handling
- Downstream bash `bar_char()` handles non-numeric "X" with red error indicator
- `fmt_quota_pct()` passes "X" through without appending "%"
- Dockerfile uses ENTRYPOINT for the binary, CMD for default args (Docker exec form)

### Micro-Decisions
- Added packages.find section to pyproject.toml to prevent setuptools flat-layout picking up `deploy/` directory
- launchd sed specifically matches `~/.local/bin/tmux-status-server` rather than a generic `~` replacement to avoid unintended substitutions
- The else clause for status fallthrough does NOT read reset times (unlike the "error" branch)
- CMD uses JSON exec form `["--host", "0.0.0.0"]` for proper signal handling in Docker

### Code Landmarks
- `server/pyproject.toml` — Package metadata, deps, console script entry point, packages.find section
- `server/tmux_status_server/config.py` — CLI arg parsing and network exposure warning
- `server/tmux_status_server/scraper.py` — Session key reading and quota fetching
- `server/tmux_status_server/server.py` — QuotaServer class, HTTP endpoints, auth, polling
- `server/Dockerfile` — ENTRYPOINT + CMD, binds 0.0.0.0 by default
- `scripts/tmux-claude-status` — Renderer with HTTP fetch, settings parsing, quota status handling (lines 186-204)
- `install.sh` — Installer with server pip install, daemon setup, launchd sed fix
- `uninstall.sh` — Uninstaller with daemon teardown

### Test State
- 226 tests pass: `source ~/.venv/bin/activate && python3 -m pytest server/tests/ -q`
- No flaky tests
- Test files: test_config.py, test_scraper.py, test_package.py, test_server.py, test_deploy.py

## What's Next
- TS-19: Fix install.sh hardcoded path — unquoted heredoc delimiter for variable expansion
- TS-20: Expand warn_if_exposed safe addresses — add localhost, ::1
- TS-21: Reset stale org UUID on auth errors
- 3 fix stories remaining, all independent (wave 1)
