# Handoff: Review -> Triage (Pass 2)

## Context

Second static analysis review after fix cycle 1 resolved 7 findings from the first review. Review performed against DESIGN.md, IDEA.md, and all implementation files. 292 tests now pass.

## Key Decisions for Triage

### Critical (2 findings)

1. **API key auth is completely bypassed** (`server/tmux_status_server/server.py:74-84`): Bottle's `before_request` hooks discard return values — the route handler always executes regardless. Auth check returns 401 JSON but the route overwrites it with real quota data. Fix: use `abort(401)` instead of `return` (one-line change, `abort` already imported).

2. **Auth tests verify the wrong thing** (`server/tests/test_server.py:518-573`): Tests call the hook function directly and assert on return value, which Bottle ignores. All 235 original tests pass despite auth being completely broken. Fix: add integration tests with real HTTP requests.

### Important (3 findings)

3. **SIGTERM doesn't shut down HTTP server** (`server.py:162-166`): Custom signal handler sets flags but `serve_forever()` doesn't check them. Server is unkillable via `kill`. Fix: raise `KeyboardInterrupt` or call `os._exit(0)` in handler.

4. **Renderer crashes on None utilization** (`scripts/tmux-claude-status:189,193`): When upstream returns missing data, `round(None)` raises TypeError. Status bar goes blank. Fix: guard with `if fh_util is None or fh_util == "X"`.

5. **Empty API key file enables auth bypass** (`server.py:56-64`): Empty key file -> `hmac.compare_digest("", "")` -> True. Fix: return None for empty keys in `_load_api_key`.

### Useful (3 findings)

6. pip install stderr suppressed in install.sh
7. Private API coupling: `_error_bridge` import
8. API key file not permission-checked (unlike session key file)

## Design Alignment

MINOR DRIFT — auth mechanism follows design spec exactly, but the design's assumption about Bottle `before_request` hook semantics is wrong. All other aspects closely aligned.

## Artifacts

- `.forge/REVIEW-REPORT.md` — Full review with 8 findings, severity ratings, and solution options
