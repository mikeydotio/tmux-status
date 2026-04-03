# Handoff: Review -> Triage

## Context

Static analysis review of the tmux-status-server implementation (9 stories, 188 tests passing). Review performed against DESIGN.md, IDEA.md, and all implementation files.

## Key Decisions for Triage

### Critical (2 findings)

1. **pyproject.toml build backend is broken** (`server/pyproject.toml:3`): Uses `"setuptools.backends._legacy:_Backend"` which does not exist in standard setuptools. `pip install server/` will fail. Fix: change to `"setuptools.build_meta"`. This is a one-line fix.

2. **launchd plist tilde in ProgramArguments** (`server/deploy/io.mikey.tmux-status-server.plist:9`): launchd does not expand `~`, so the daemon will fail to start on macOS. Fix: have install.sh substitute `~` with the actual home directory before copying.

### Important (4 findings)

3. **Renderer ignores most error statuses** (`scripts/tmux-claude-status:186-201`): Only handles `"ok"` and `"error"`, but server returns `"expired"`, `"blocked"`, `"rate_limited"`, etc. These show as "0%" instead of "X%". Fix: add an `else` clause for non-"ok" statuses.

4. **Dockerfile bind 127.0.0.1 unreachable** (`server/Dockerfile:13`): Server defaults to localhost, which is unreachable from outside Docker. Fix: add `CMD ["--host", "0.0.0.0"]`.

5. **Stale org UUID cache** (`server/tmux_status_server/scraper.py:21`): Module-level `_org_uuid` never invalidated on auth errors. Fix: reset on 401/403 from usage endpoint.

6. **QUOTA_API_KEY plaintext in settings.conf** (`config/settings.example.conf:25`): Inconsistent with server-side file-based approach. Consider adding `QUOTA_API_KEY_FILE`.

### Useful (5 findings)

7-11. Minor items: localhost check only covers "127.0.0.1", unused imports in `__main__.py`, module-level global state, no graceful Bottle shutdown, hardcoded path in install.sh source line.

## Design Alignment

MINOR DRIFT. Main gap: renderer doesn't handle the full error status vocabulary from the server (finding #3). The "X" error signaling design is partially broken in the rendering path.

## Artifacts

- `/home/mikey/tmux-status/.forge/REVIEW-REPORT.md` — Full review with 11 findings, severity ratings, and solution options
