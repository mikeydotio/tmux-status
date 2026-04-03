# Review Report

## Summary

The tmux-status-server codebase is well-structured and closely follows the design document. The server, scraper, config, and client integration are clean, modular, and well-tested (188 tests, all passing). However, there are a few issues ranging from a broken build backend in pyproject.toml (critical for installation), to a launchd plist that will not work on macOS, to a renderer status-handling gap that silently drops error data for several server error states.

## Findings

### 1. pyproject.toml Uses Non-Standard Build Backend

- **Severity**: Critical
- **Description**: The `build-backend` in `server/pyproject.toml` is set to `"setuptools.backends._legacy:_Backend"`. This module path does not exist in standard setuptools distributions. The canonical backend is `"setuptools.build_meta"`. Running `pip install server/` will fail on most systems because the build backend cannot be resolved.
- **Location**: `server/pyproject.toml:3`
- **Option 1 (Recommended)**: Change to `build-backend = "setuptools.build_meta"` -- Pros: standard, works with all pip/setuptools versions. Cons: none.
- **Option 2**: Change to `build-backend = "setuptools.build_meta:__legacy__"` -- Pros: enables legacy setup.py compatibility. Cons: unnecessary since there is no setup.py.

### 2. launchd Plist Uses Tilde (`~`) in ProgramArguments

- **Severity**: Critical
- **Description**: The launchd plist at `server/deploy/io.mikey.tmux-status-server.plist` uses `~/.local/bin/tmux-status-server` as the program path. launchd does NOT perform tilde expansion in `ProgramArguments`. This means the server daemon will fail to start on macOS with "file not found". The `install.sh` copies this file verbatim.
- **Location**: `server/deploy/io.mikey.tmux-status-server.plist:9`, `install.sh:264`
- **Option 1 (Recommended)**: Have `install.sh` perform `sed` substitution to replace `~` with `$HOME` before copying the plist to `~/Library/LaunchAgents/`. The template stays generic, the installed version gets an absolute path. -- Pros: works correctly, template remains portable. Cons: slightly more install logic.
- **Option 2**: Use `/bin/sh -c` wrapper in ProgramArguments: `["/bin/sh", "-c", "exec ~/.local/bin/tmux-status-server"]` -- Pros: no install.sh changes needed. Cons: extra process, slightly less clean.
- **Option 3**: Change the plist template to use `$HOME` placeholder and have install.sh substitute it. -- Pros: explicit. Cons: same as Option 1 really.

### 3. Renderer Ignores Non-"ok" / Non-"error" Server Statuses

- **Severity**: Important
- **Description**: The renderer's Python block in `scripts/tmux-claude-status` only handles `quota_status == "ok"` and `quota_status == "error"` (lines 186-201). However, the server returns statuses like `"expired"`, `"session_key_expired"`, `"blocked"`, `"rate_limited"`, `"upstream_error"`, `"starting"`, and `"no_key"`. When any of these non-"ok"/non-"error" statuses are received, the renderer falls through to default values (`five_hour_pct = 0`, `seven_day_pct = 0`), rendering misleading "0%" quota bars instead of "X%". The bash status color logic (line 294) correctly lists `expired|blocked|error|rate_limited|key_expired`, but the Python data extraction never populates the "X" values for these statuses.
- **Location**: `scripts/tmux-claude-status:186-201` (Python block), `scripts/tmux-claude-status:294-296` (bash block)
- **Option 1 (Recommended)**: Change the Python block to use an `else` clause that sets `five_hour_pct = "X"` and `seven_day_pct = "X"` for any non-"ok" status, and still extracts `resets_at` from the response. This is a 3-line change. -- Pros: handles all current and future error statuses. Cons: none.
- **Option 2**: Enumerate all known error statuses explicitly (elif chain). -- Pros: explicit. Cons: fragile, must update when new statuses are added.

### 4. Dockerfile Default Bind Address is 127.0.0.1 (Unreachable in Docker)

- **Severity**: Important
- **Description**: The server defaults to `--host 127.0.0.1`. When run inside a Docker container (via the provided `server/Dockerfile`), this makes the server unreachable from outside the container, even with `-p 7850:7850` port mapping. Docker port mapping requires the server to bind to `0.0.0.0` inside the container.
- **Location**: `server/Dockerfile:13`, `server/tmux_status_server/config.py:14`
- **Option 1 (Recommended)**: Add `CMD ["--host", "0.0.0.0"]` to the Dockerfile after the ENTRYPOINT, so Docker deployments default to binding all interfaces while the bare binary still defaults to localhost. -- Pros: safe default for both modes. Cons: none.
- **Option 2**: Set `ENV TMUX_STATUS_HOST=0.0.0.0` in the Dockerfile and read it in config. -- Pros: overridable. Cons: requires adding env var support to config.py.

### 5. Stale Org UUID Cache After Auth Errors

- **Severity**: Important
- **Description**: The scraper caches `_org_uuid` at module level (line 21 of `scraper.py`) and never invalidates it. If a user switches accounts or the org UUID changes, the server will keep hitting the usage endpoint with the old UUID, returning `upstream_error` forever until restarted. More critically, if the session key expires (401), the org UUID is still cached from the successful discovery, so subsequent calls skip org discovery and go straight to the usage endpoint -- which might work if the key is refreshed for the same org, but fails silently for an org switch.
- **Location**: `server/tmux_status_server/scraper.py:21,129-138`
- **Option 1 (Recommended)**: Reset `_org_uuid = None` when a 401 or 403 is received on the `/usage` endpoint, forcing re-discovery on the next cycle. -- Pros: self-healing on key rotation. Cons: one extra API call on re-auth.
- **Option 2**: Clear the cache on any error from the usage endpoint. -- Pros: most resilient. Cons: extra org discovery call on transient errors.
- **Option 3**: Make `_org_uuid` an instance variable on `QuotaServer` instead of a module global, passed into `fetch_quota()`. -- Pros: cleaner architecture, testable. Cons: larger refactor.

### 6. QUOTA_API_KEY Stored in Plaintext in settings.conf

- **Severity**: Important
- **Description**: The `QUOTA_API_KEY` setting in `settings.conf` stores the API key as plaintext in a config file. This is inconsistent with the server-side approach where `--api-key-file` is explicitly preferred over CLI flags or env vars for security (design document "Credential Protection" section). On the client side, the API key is readable by anyone who can read `~/.config/tmux-status/settings.conf`.
- **Location**: `config/settings.example.conf:25`, `scripts/tmux-claude-status:127-128`
- **Option 1 (Recommended)**: Add a `QUOTA_API_KEY_FILE` setting that reads the key from a file (mirroring the server's approach), and deprecate `QUOTA_API_KEY`. The renderer already runs Python, so reading a file is trivial. -- Pros: consistent security model. Cons: slightly more config.
- **Option 2**: Document that `settings.conf` should be `chmod 600` and add a permissions check in the renderer. -- Pros: simple. Cons: plaintext key still in a config file.
- **Option 3**: Accept the current approach as adequate for client-side use cases (the key only protects access to quota data, not credentials). Add a comment documenting the trade-off. -- Pros: no code changes. Cons: inconsistent security posture.

### 7. warn_if_exposed Only Checks "127.0.0.1" Literal

- **Severity**: Useful
- **Description**: The `warn_if_exposed()` function only checks `args.host != "127.0.0.1"`. Users binding to `localhost`, `::1` (IPv6 loopback), or `127.0.0.2` will get a spurious warning. Conversely, the check is sufficient for the common case, and the warning is informational only.
- **Location**: `server/tmux_status_server/config.py:86`
- **Option 1 (Recommended)**: Expand the check to also accept `"localhost"` and `"::1"` as safe bind addresses. -- Pros: correct for common cases. Cons: minor code change.
- **Option 2**: Keep as-is, document that the check is conservative and the warning is advisory. -- Pros: no change. Cons: false positives.

### 8. __main__.py Imports parse_args and warn_if_exposed But Does Not Use Them

- **Severity**: Useful
- **Description**: `server/tmux_status_server/__main__.py` imports `parse_args` and `warn_if_exposed` from `config` but never calls them directly. It delegates entirely to `_server_main()` (which is `server.main()`), and that function handles its own argument parsing. The unused imports add confusion about the entry point flow.
- **Location**: `server/tmux_status_server/__main__.py:3`
- **Option 1 (Recommended)**: Remove the unused imports. The `__main__.py` only needs to import and call `_server_main`. -- Pros: cleaner code. Cons: some tests check for these imports in `__main__.py` (test_package.py:78-106), so those tests would need updating.
- **Option 2**: Keep as-is since tests verify their presence. -- Pros: no test changes. Cons: misleading imports remain.

### 9. Scraper Module-Level Global State Complicates Testing

- **Severity**: Useful
- **Description**: The `_org_uuid` module-level global in `scraper.py` requires tests to manually reset it in `setUp()` (`scraper._org_uuid = None`). This is fragile and creates hidden coupling between test classes. The test suite handles this correctly today, but it is a maintenance risk.
- **Location**: `server/tmux_status_server/scraper.py:21`
- **Option 1 (Recommended)**: Make `_org_uuid` an instance attribute on a `Scraper` class or pass it through `QuotaServer`. The server already re-reads the session key each cycle; it could similarly manage the org UUID. -- Pros: eliminates global state, easier testing. Cons: moderate refactor.
- **Option 2**: Keep as-is since all current tests handle it properly. -- Pros: no change. Cons: tech debt.

### 10. No Graceful Shutdown of Bottle Server

- **Severity**: Useful
- **Description**: The `_handle_sigterm` method sets the shutdown event and wakes the poll thread, but there is no explicit mechanism to stop the Bottle server. Bottle's built-in WSGIRef server does not have a clean shutdown API. On SIGTERM, the poll thread exits cleanly, but the Bottle server thread keeps running until the process is forcibly killed. In practice, systemd/launchd will send SIGKILL after a timeout, so this works but is not graceful.
- **Location**: `server/tmux_status_server/server.py:162-166,193`
- **Option 1 (Recommended)**: Accept this as a known limitation and add a comment. Bottle's built-in server is designed for development/light use; the 5-10 second shutdown delay is acceptable for this use case. -- Pros: no code change. Cons: not perfectly clean.
- **Option 2**: Use Bottle's `server_close()` or switch to a server adapter that supports graceful shutdown (e.g., `cheroot`). -- Pros: clean shutdown. Cons: adds dependency or complexity.

### 11. install.sh Source Line Hardcodes ~/projects/tmux-status Path

- **Severity**: Useful
- **Description**: The `source-file` line appended to tmux.conf (line 159) hardcodes `~/projects/tmux-status/overlay/status.conf`. If the user installs to a custom `TMUX_STATUS_DIR`, this path will be wrong. The variable `INSTALL_DIR` is already set correctly; the heredoc should use it.
- **Location**: `install.sh:159`
- **Option 1 (Recommended)**: Replace the hardcoded path with `$INSTALL_DIR/overlay/status.conf` in the appended tmux.conf line. -- Pros: respects custom install directories. Cons: none.
- **Option 2**: Keep as-is since the default path works for most users. -- Pros: no change. Cons: broken for custom TMUX_STATUS_DIR.

## Design Alignment

**MINOR DRIFT** -- The implementation closely follows the design document with the following deviations:

1. **Renderer status handling gap**: The design specifies error signaling via `"X"` utilization values for all error statuses. The renderer only parses `"X"` for `status == "ok"` (where utilization could theoretically be "X") and `status == "error"`. Server error statuses like `"expired"`, `"blocked"`, `"rate_limited"` etc. fall through to defaults of 0, not "X". This contradicts the design's error signaling table.

2. **IDEA.md standalone mode**: The IDEA.md document mentions standalone mode (no `QUOTA_SOURCE`) should work unchanged. The design document explicitly removed standalone mode ("no standalone mode vs client mode -- only one architecture"). The implementation follows the design (always server), which is the correct choice, but creates a delta from the original requirements. This is an intentional design decision, not a defect.

3. **API key security asymmetry**: The server uses `--api-key-file` (file-based, recommended in design's security section), while the client uses `QUOTA_API_KEY` as plaintext in `settings.conf`. The design mentions `--api-key-file` preference but doesn't explicitly address the client-side storage.

## Strengths

- **Clean module separation**: config, scraper, server, and `__main__` are well-decomposed with clear single responsibilities.
- **Error sanitization**: Error responses consistently use machine-readable codes. Raw exception text never leaks into API responses or cache files. Tests explicitly verify this.
- **Session key permission checking**: The `read_session_key()` function properly validates file permissions (0o077 mask), rejecting group/world-readable files.
- **Comprehensive test coverage**: 188 tests covering config parsing, scraper behavior, server endpoints, auth, signal handling, deployment files, and package structure. Tests are well-organized and use proper mocking.
- **Atomic writes**: Both server-side cache and client-side disk cache use temp-file + `os.replace()` for safe concurrent access.
- **Timing-safe auth**: API key comparison uses `hmac.compare_digest()` as specified.
- **Lazy imports**: Bottle and curl_cffi are imported lazily inside methods, avoiding import-time failures when dependencies are missing.
- **Silent failure in renderer**: The client fetch function follows the "silent failure" pattern correctly -- any exception falls through to stale cache, no error output.
- **Signal handling**: SIGTERM/SIGINT/SIGUSR1 are all handled correctly, with SIGUSR1 providing out-of-cycle refresh capability.
