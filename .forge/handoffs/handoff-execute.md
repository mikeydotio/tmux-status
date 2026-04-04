# Work Handoff

## Session Summary
- **Session**: session-fix1-001
- **Stories completed**: 1 (TS-15)
- **Stories attempted**: 1
- **Status**: Session limit reached (1/1 stories per session)

## What Happened
Fix cycle 1, session 1. Implemented TS-15 (pyproject.toml build backend fix). Changed build-backend from `setuptools.backends._legacy:_Backend` to `setuptools.build_meta`. Also added `[tool.setuptools.packages.find]` section to explicitly include only `tmux_status_server*` packages (setuptools flat-layout discovery was picking up the `deploy` directory). Passed evaluation on first attempt.

## Stories Completed This Session
- TS-15: Fix pyproject.toml build backend — changed build-backend to `setuptools.build_meta`, added packages.find section

## Fix Cycle 1 Progress
- TS-15: Done (this session) — pyproject.toml build backend
- TS-16: Todo — launchd plist tilde expansion
- TS-17: Todo — renderer status fallthrough
- TS-18: Todo — Dockerfile bind address
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
- pyproject.toml now uses `[tool.setuptools.packages.find]` with explicit include

### Micro-Decisions
- Added packages.find section to pyproject.toml to prevent setuptools flat-layout picking up `deploy/` directory

### Code Landmarks
- `server/pyproject.toml` — Package metadata, deps, console script entry point, packages.find section
- `server/tmux_status_server/config.py` — CLI arg parsing and network exposure warning
- `server/tmux_status_server/scraper.py` — Session key reading and quota fetching
- `server/tmux_status_server/server.py` — QuotaServer class, HTTP endpoints, auth, polling
- `scripts/tmux-claude-status` — Renderer with HTTP fetch, settings parsing
- `install.sh` — Installer with server pip install, daemon setup
- `uninstall.sh` — Uninstaller with daemon teardown

### Test State
- 223 tests pass: `source ~/.venv/bin/activate && python3 -m pytest server/tests/ -q`
- No flaky tests
- Test files: test_config.py, test_scraper.py, test_package.py, test_server.py, test_deploy.py

## What's Next
- TS-16: Fix launchd plist tilde expansion in install.sh
- 6 fix stories remaining, all independent (wave 1)
