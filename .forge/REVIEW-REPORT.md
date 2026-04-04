# Review Report

## Summary

The quota data server is well-structured and follows DESIGN.md closely, with one critical exception: **the API key authentication is completely bypassed** due to Bottle's `before_request` hook semantics discarding return values. Additionally, the SIGTERM signal handler does not shut down the HTTP server, and the renderer crashes on `None` utilization values.

## Findings

### 1. API Key Authentication Bypass — Route Handler Executes Despite Auth Failure
- **Severity**: Critical
- **Description**: The `before_request` hook at line 74 attempts to block unauthenticated requests by returning a 401 JSON body. However, Bottle's `trigger_hook()` discards all return values from `before_request` hooks. The request proceeds to the route handler, which overwrites the response body with actual quota data. The client receives the real `/quota` data with a 401 status code.
- **Location**: `server/tmux_status_server/server.py:74-84`
- **Option 1 (Recommended)**: Replace the return statement with `abort(401, ...)` or raise `bottle.HTTPResponse(...)`. The `abort()` function is already imported at line 68 but never used. This raises an exception that Bottle catches, preventing the route handler from executing.
- **Option 2**: Use a Bottle plugin/decorator that wraps each route and checks auth before calling the route function. More code but more explicit control flow.

### 2. Auth Tests Verify the Wrong Thing (Mock Gives False Confidence)
- **Severity**: Critical
- **Description**: The auth tests call `hooks["before_request"]()` directly and assert the return value is non-None JSON. But Bottle ignores this return value, so these tests verify behavior that does not affect the real system. No integration test sends an actual HTTP request through the Bottle app to verify that unauthenticated requests receive a 401 body *without* the quota data.
- **Location**: `server/tests/test_server.py:518-573` (class `TestAuthHook`)
- **Option 1 (Recommended)**: Add integration tests using `webtest.TestApp(app)` that send real HTTP requests and verify the response body does NOT contain quota data when auth fails.
- **Option 2**: Add a test that imports Bottle, creates a real app with the `before_request` hook, and verifies via `app._handle()` that the route handler output is NOT returned when auth fails.

### 3. SIGTERM Does Not Actually Shut Down the HTTP Server
- **Severity**: Important
- **Description**: The `_handle_sigterm` signal handler sets `self._shutdown` and `self._wake`, which stops the background poll thread. However, the main thread is blocked in `bottle.run()` -> `serve_forever()`, which does not check `self._shutdown`. Python's default SIGTERM handler raises `SystemExit`, but installing a custom handler overrides this. The server is unkillable via `kill` — systemd will wait for `TimeoutStopSec` then SIGKILL.
- **Location**: `server/tmux_status_server/server.py:162-166, 193`
- **Option 1 (Recommended)**: In `_handle_sigterm`, after setting the shutdown event, call `os._exit(0)` or `sys.exit(0)` or raise `KeyboardInterrupt` to let `serve_forever()` handle it.
- **Option 2**: Store a reference to the WSGI server and call `self._srv.shutdown()` from the signal handler.

### 4. Renderer Crashes on `None` Utilization from Server
- **Severity**: Important
- **Description**: When the upstream API is missing the `five_hour` or `seven_day` key, the scraper returns `{"utilization": None, ...}`. The renderer checks `if fh_util == "X"` — `None` is not `"X"`, so it falls to `round(None)` which raises `TypeError`. The status bar goes blank.
- **Location**: `scripts/tmux-claude-status:189, 193`
- **Option 1 (Recommended)**: Add a guard: `five_hour_pct = "X" if fh_util is None or fh_util == "X" else round(fh_util)`. Same for `seven_day`.
- **Option 2**: In the scraper's `extract_window`, default `utilization` to 0 instead of None.

### 5. Empty API Key File Enables Auth With Empty String
- **Severity**: Important
- **Description**: `_load_api_key` returns `""` for an empty or whitespace-only key file. Since `"" is not None`, the auth hook runs. `hmac.compare_digest("", "")` is `True`, so sending an empty `X-API-Key` header passes auth.
- **Location**: `server/tmux_status_server/server.py:56-64`
- **Option 1 (Recommended)**: After loading the API key, check if it's empty and return None: `if not key: logger.warning("API key file is empty, auth disabled"); return None`.
- **Option 2**: Refuse to start if the API key file is empty. Stricter but prevents misconfiguration.

### 6. pip install stderr suppressed in install.sh
- **Severity**: Useful
- **Description**: `install.sh:227,231` suppresses pip install stderr with `2>/dev/null`. Users cannot diagnose installation failures.
- **Location**: `install.sh:227,231`
- **Option 1 (Recommended)**: Redirect stderr to a log file instead of /dev/null.
- **Option 2**: Show stderr but capture it for later display on failure.

### 7. Private API coupling: _error_bridge import
- **Severity**: Useful
- **Description**: `server.py:22` imports the private function `_error_bridge` from `scraper.py`. Underscore-prefixed names are conventionally private.
- **Location**: `server/tmux_status_server/server.py:22`
- **Option 1 (Recommended)**: Rename to `error_bridge` (public API).
- **Option 2**: Move to a shared module.

### 8. API key file not permission-checked
- **Severity**: Useful
- **Description**: The `--api-key-file` is not permission-checked, unlike the session key file which requires `0o600`. The design doc says "File should be `chmod 600`" but this is not enforced.
- **Location**: `server/tmux_status_server/server.py:56-64`
- **Option 1 (Recommended)**: Add `0o600` permission check matching `read_session_key` pattern.
- **Option 2**: Log a warning for world-readable API key files without blocking startup.

## Design Alignment

**MINOR DRIFT** — The codebase implements the DESIGN.md architecture faithfully with one significant exception: the auth mechanism described in the design ("checked via `hmac.compare_digest()` in a Bottle `before_request` hook") is correctly implemented as specified, but the specified approach is broken due to Bottle's hook semantics. The design assumed `before_request` hook return values would short-circuit request handling, which is not how Bottle works.

## Strengths

- **Atomic writes**: Both the server (reference swap under GIL) and client (`tmp + os.replace`) use atomic write patterns correctly.
- **Error sanitization**: The scraper consistently uses generic error codes and never leaks raw exception text in API responses.
- **Session key permission validation**: `read_session_key` checks `st_mode & 0o077` before reading credentials.
- **Comprehensive test suite**: 292 tests covering config parsing, scraper logic, server endpoints, deployment files, and package structure.
- **Silent failure in renderer**: Correctly exits 0 and outputs nothing when data is unavailable.
- **SIGUSR1 immediate-scrape**: Well-designed operational control mechanism.
