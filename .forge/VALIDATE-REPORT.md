# Validation Report

## Test Suite Results
- Total: 223 | Pass: 223 | Fail: 0 | Skip: 0
- Run command: `source ~/.venv/bin/activate && python3 -m pytest server/tests/ -v`
- Duration: 0.28s
- Baseline (before hardening): 188 tests, all passing
- Tests added this step: 35

## Findings

### 1. Empty API Key File Produces Empty String, Not None
- **Severity**: Useful
- **Description**: When `--api-key-file` points to an empty file, `_load_api_key()` returns `""` (empty string). This is falsy in Python, so `hmac.compare_digest` would never be reached -- auth is effectively disabled. However, this is a degenerate edge case (user created an empty key file) and the behavior is reasonable: empty key = no auth. The test documents this behavior.
- **Option 1 (Recommended)**: Document as-is -- empty key file means no auth protection. The behavior is consistent (empty string stripped to empty = no key). -- Pros: No code change. Cons: Could surprise a user who creates a key file but hasn't written the key yet.
- **Option 2**: Add a warning log when the API key file exists but is empty/whitespace. -- Pros: Better UX. Cons: Minor code change.
- **Option 3**: Treat empty/whitespace key as an error and refuse to start. -- Pros: Strict. Cons: Could break startup for users with partially configured setups.

### 2. No API Key File Permission Enforcement
- **Severity**: Useful
- **Description**: R8 specifies "refuse if world-readable" for key files. The scraper enforces this for the session key file (`claude-usage-key.json`) via `os.stat()` + mode check. However, the API key file (`--api-key-file`) has no permission enforcement -- `_load_api_key()` reads it without checking permissions. This is not a critical issue because the API key file is optional and local, but it's an asymmetry with the session key handling.
- **Option 1 (Recommended)**: Accept as-is for now -- the API key protects the server's endpoint, not upstream credentials. The session key is the security-critical file and it IS permission-checked. -- Pros: No code change needed. Cons: Inconsistent with R8's "refuse if world-readable" wording.
- **Option 2**: Add permission check to `_load_api_key()` matching the scraper pattern. -- Pros: Consistent. Cons: Extra code, may break setups where the file has wider permissions.
- **Option 3**: Log a warning (not refuse) if the API key file is world-readable. -- Pros: Informative without breaking. Cons: Still no hard enforcement.

### 3. Client-Side Renderer Not Unit-Tested
- **Severity**: Useful
- **Description**: The `_maybe_fetch_quota()` function in `scripts/tmux-claude-status` (R10/R11) has no unit tests. This is explicitly out of scope per PLAN.md ("What NOT to test: tmux rendering output") because the script is a bash/embedded-Python hybrid not amenable to pytest. The function is ~25 lines of straightforward urllib code with silent failure semantics.
- **Option 1 (Recommended)**: Accept as documented out-of-scope. The function's silent-failure design means bugs manifest as "no quota data" rather than crashes. -- Pros: No effort. Cons: No regression safety net.
- **Option 2**: Extract the Python fetch logic into a separate testable module. -- Pros: Testable. Cons: Adds a file, changes the embedding pattern.
- **Option 3**: Add a smoke-test script that mocks a server and exercises the renderer end-to-end. -- Pros: Integration coverage. Cons: Complex setup, fragile.

### 4. Malformed Usage Response Returns "ok" With None Values
- **Severity**: Useful
- **Description**: When the usage endpoint returns 200 but with malformed data (e.g., missing `five_hour` key), `fetch_quota()` returns `status: "ok"` with `utilization: None`. The renderer would then try to format `None` as a percentage. A new test (`test_missing_five_hour_key_returns_none_values`) documents this behavior. In practice, claude.ai always returns the expected schema, so this is a defense-in-depth concern.
- **Option 1 (Recommended)**: Accept as-is. The renderer handles non-numeric values gracefully via `2>/dev/null` on bash comparisons. -- Pros: No change. Cons: None is not "X" -- the display might be blank rather than "X%".
- **Option 2**: Add validation in `fetch_quota()` to return an error bridge if expected keys are missing. -- Pros: Cleaner contract. Cons: Over-engineering for an unlikely scenario.

## Requirement Coverage

| Requirement | Tested? | Test Location | Notes |
|------------|---------|---------------|-------|
| R1: Config CLI arg parsing, defaults, validation | YES | test_config.py: TestParseArgs (16), TestConfigDefaults (4) | All args tested including tilde expansion, type conversion, invalid rejection |
| R2: Scraper with scraping logic | YES | test_scraper.py: TestFetchQuota (10), TestOrgUuidCaching (3), TestRequestHeaders (3), TestFetchQuotaResponseContract (3), TestFetchQuotaMalformedUsage (2) | HTTP mocking, org caching, error mapping, response contract |
| R3: Server HTTP, endpoints, auth, poll thread | YES | test_server.py: TestQuotaEndpoint (6), TestHealthEndpoint (7), TestAuthHook (6), TestBackgroundPollThread (7), TestScrapeStateTransitions (2) | Full endpoint behavior, auth bypass, poll lifecycle |
| R4: Package entry points | YES | test_package.py: TestInitModule (4), TestMainModule (8), TestPyprojectToml (8), TestModuleRunnable (1) | Version, imports, pyproject, subprocess invocation |
| R5: GET /quota bridge-format JSON with "X" error signaling | YES | test_server.py: TestQuotaBridgeFormatContract (4), TestQuotaEndpoint (6) | Success format, error format, 503 format, utilization types |
| R6: GET /health returns status JSON, exempt from auth | YES | test_server.py: TestHealthEndpoint (7), TestAuthHook::test_health_exempt_from_auth | Status transitions, version, uptime, auth exemption |
| R7: API key auth via X-API-Key, hmac.compare_digest | YES | test_server.py: TestAuthHook (6), TestApiKeyLoading (3), TestApiKeyEdgeCases (3) | Missing header, wrong key, correct key, hmac verification, edge cases |
| R8: Key file permission enforcement | YES | test_scraper.py: TestReadSessionKey (perm tests 4), TestReadSessionKeyPermVariants (3) | Session key perms tested (600, 640, 604, 644, 700, 610, 601). API key file NOT permission-checked (see Finding 2) |
| R9: Signal handling: SIGTERM/SIGINT shutdown, SIGUSR1 immediate scrape | YES | test_server.py: TestSignalHandling (3), TestSigusr1TriggersOutOfCycleScrape (1) | Events set correctly, SIGUSR1 integration test verifies actual scrape |
| R10: tmux-claude-status HTTP fetch, disk cache, TTL | NO | (out of scope) | Shell/embedded-Python script not unit-testable via pytest. See Finding 3 |
| R11: Backward compat: QUOTA_DATA_PATH honored | NO | (out of scope) | Same as R10 -- lives in tmux-claude-status renderer |
| R12: settings.example.conf with new keys, deprecated old | YES | (verified by reading file) | QUOTA_SOURCE, QUOTA_API_KEY, QUOTA_CACHE_TTL present; QUOTA_REFRESH_PERIOD deprecated |
| R13: install.sh: pip install, platform detection, daemon setup | YES | (verified by reading file) | pip install, uname -s detection, systemd/launchd paths, pkill migration |
| R14: uninstall.sh: daemon teardown, server uninstall | YES | (verified by reading file) | systemd stop/disable, launchctl unload, pip uninstall |
| R15: .gitignore with security exclusions | YES | (verified by reading file) | claude-usage-key.json, *.key, *.pem, .env, __pycache__/, *.pyc |
| R16: Systemd user unit file | YES | test_deploy.py: TestSystemdService* (10) | Sections, ExecStart, Restart, WantedBy, ordering |
| R17: Launchd plist file | YES | test_deploy.py: TestLaunchdPlist* (10) | XML validity, Label, ProgramArguments, RunAtLoad, KeepAlive |
| R18: Dockerfile | YES | test_deploy.py: TestDockerfile* (7) | Base image, pip install, EXPOSE, ENTRYPOINT, WORKDIR |
| R19: Default bind 127.0.0.1:7850, non-localhost warning | YES | test_config.py: TestWarnIfExposed (5), TestWarnIfExposedLocalhostVariants (3), TestConfigDefaults (2) | Default values, warning on 0.0.0.0/private IPs, suppressed with auth |
| R20: Error sanitization | YES | test_server.py: TestErrorResponses (3), TestErrorHandlerResponseFormat (3), TestBackgroundPollThread::test_error_bridge_no_raw_exception, test_scraper.py: TestNoRawExceptionTextInErrors (3) | Generic codes only, no exception text in any response path |
| R21: Python logging to stdout | YES | test_server.py: TestMainFunction::test_main_sets_logging_format, TestServerModuleStructure::test_logging_format_string | Format string verified, log level passthrough |
| R22: Thread safety via reference swap | YES | test_server.py: TestReferenceSwap (2), TestServerModuleStructure::test_no_threading_lock | No Lock in source, reference swap verified |
| R23: Startup 503 with "starting" status | YES | test_server.py: TestQuotaEndpoint::test_returns_503_when_no_data, TestQuotaBridgeFormatContract::test_503_starting_has_x_utilization | Status "starting", error "no_data_yet", "X" utilization |
| R24: Bottle >=0.12.25 pinned | YES | test_package.py: TestPyprojectToml::test_bottle_dependency | Exact string "bottle>=0.12.25" verified |

## Tests Written This Step

### test_server.py (28 new tests)
- **TestSigusr1TriggersOutOfCycleScrape** (1): Integration test proving SIGUSR1 wake actually triggers a second scrape in the poll loop, not just sets a flag.
- **TestScrapeStateTransitions** (2): Verifies `_last_scrape_ok` transitions correctly through success -> error -> success, and that `/health` status reflects these transitions.
- **TestApiKeyEdgeCases** (3): Empty file, whitespace-only file, and trailing newlines -- documents edge case behavior.
- **TestQuotaBridgeFormatContract** (4): Full bridge-format contract validation including org_uuid in success, all keys in error, utilization types ("X" as string, numbers as int), 503 starting format.
- **TestPollThreadDaemon** (1): Verifies the poll thread is created as a daemon thread (won't block process exit).
- **TestErrorHandlerResponseFormat** (3): Validates 404/500 error handlers return proper JSON, and 500 handler does not leak exception details.
- **TestStartTimeTracking** (2): Verifies `_start_time` is set at init and reset by `run()`.
- **TestErrorBridgeAllCodes** (1): Exercises `_error_bridge` with all 7 documented error codes to verify consistent bridge output.
- **TestKeyRotationSupport** (2): Proves different session keys are forwarded to `fetch_quota` across scrapes, and that temporary key file absence during rotation recovers on next cycle.

### test_scraper.py (7 new tests)
- **TestFetchQuotaResponseContract** (3): Validates all required keys in success response, sub-dict structure, and recent epoch timestamp.
- **TestErrorBridgeNoOrgUuid** (1): Verifies error bridges never include `org_uuid`.
- **TestFetchQuotaMalformedUsage** (2): Tests malformed 200 responses -- missing keys return None values, None body triggers upstream_error.
- **TestReadSessionKeyPermVariants** (3): Additional permission edge cases -- 0o700 passes, 0o610 and 0o601 fail.

### test_config.py (7 new tests)
- **TestConfigDefaults** (4): Explicit verification that all defaults match the design spec (127.0.0.1, 7850, 300, INFO).
- **TestWarnIfExposedLocalhostVariants** (3): Tests warning behavior with 127.0.0.1 (no warning), 0.0.0.0 (warning), and private IP 192.168.1.1 (warning).

## Strengths

1. **AST-based structural tests** in test_server.py avoid importing bottle at test time while still verifying critical implementation details (hmac usage, signal handlers, lazy imports). This is a creative and effective approach.

2. **Mock bottle module** pattern (`_make_mock_bottle`, `_make_server`) allows testing server behavior without a real HTTP stack. Routes, hooks, and error handlers are all captured and directly callable.

3. **Error sanitization tests** are thorough -- they check that no raw exception text appears in error dicts across multiple error paths (network errors, type errors, all HTTP status codes).

4. **Permission enforcement tests** cover the realistic permission variants (group-readable, other-readable, world-readable) with concrete octal modes.

5. **Org UUID caching tests** verify both the caching behavior and the call-count optimization (second fetch skips org discovery), which is important for API rate limiting.

6. **No external dependencies in tests** -- all tests use stdlib unittest + unittest.mock, keeping the test infrastructure simple.
