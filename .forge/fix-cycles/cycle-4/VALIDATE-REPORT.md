# Validation Report

## Test Suite Results
- Total: 362 | Pass: 362 | Fail: 0 | Skip: 0
- Run command: `python3 -m pytest tests/ -v`
- Duration: 6.44s
- Warning: 1 (deprecated `cgi` module in webob dependency — not actionable)

## Findings

### No Interval Lower Bound Validation
- **Severity**: Useful
- **Description**: `parse_args()` accepts `--interval 0` and negative values. Interval 0 causes the poll loop to scrape continuously, potentially hammering claude.ai. The old `tmux-status-quota-poll` had `MIN_INTERVAL = 30` but the new server has no such guard. The test `test_interval_zero` and `test_negative_port_accepted_by_argparse` document this as boundary behavior.
- **Option 1 (Recommended)**: Add validation: `if args.interval < 30: parser.error("--interval must be >= 30")`. Matches old behavior. — Pros: prevents accidental DoS. Cons: minor code addition.
- **Option 2**: Clamp in `QuotaServer.__init__`: `self.interval = max(30, interval)`. — Pros: defense at usage site. Cons: silently changes user input.

### Status Code Mismatch Confirmed by WSGI Tests
- **Severity**: Critical
- **Description**: `TestWSGIQuotaResponseContract::test_error_status_passes_through_wsgi` confirms the server sends `status: "session_key_expired"` through the WSGI pipeline. The renderer case pattern checks for `"expired"`. This mismatch means expired session keys don't trigger the red color indicator. (Same finding as REVIEW-REPORT.md — confirmed via end-to-end WSGI test.)
- **Option 1 (Recommended)**: Update renderer case pattern to include `session_key_expired`. — Pros: backward-compatible. Cons: longer pattern.
- **Option 2**: Change server status_map to use `"expired"`. — Pros: matches DESIGN.md. Cons: requires updating server tests.

## Requirement Coverage
| Requirement | Tested? | Test Location | Notes |
|------------|---------|---------------|-------|
| Server REST API (GET /quota) | YES | test_server.py::TestQuotaEndpoint, test_validate_cycle3.py::TestWSGIQuotaResponseContract | WSGI integration + unit |
| Server REST API (GET /health) | YES | test_server.py::TestHealthEndpoint, test_validate_cycle3.py::TestWSGIHealthContract | ok/degraded/error states |
| API key authentication | YES | test_server.py::TestAuthIntegrationWSGI, TestWSGIAuthDataLeakageExhaustive | Comprehensive: timing-safe, bypass, empty key, null byte |
| Scraper fetch_quota | YES | test_scraper.py::TestFetchQuota* | All error conditions, org UUID caching |
| Scraper read_session_key | YES | test_scraper.py::TestReadSessionKey*, test_validate_cycle3.py::TestSessionKeyInjectionPatterns | Permissions, injection, symlinks |
| Config (parse_args) | YES | test_config.py::TestParseArgs, test_validate_cycle3.py::TestConfigBoundaryValues | All flags, boundary values |
| Config (warn_if_exposed) | YES | test_config.py::TestWarnIfExposed, test_validate_gaps.py::TestWarnIfExposedExtendedHosts | localhost, ::1, 0.0.0.0 |
| Client-side fetch (_maybe_fetch_quota) | YES | test_validate_gaps.py::TestClientFetchQuota*, test_validate_cycle3.py::TestClientFetchQuota* | Happy path, TTL, silent failure, timeout, large payload, malformed URL |
| Polyglot extraction harness (TS-23) | YES | test_polyglot_extract.py | Extracts real function from tmux-claude-status |
| Signal handling (SIGTERM/SIGINT) | YES | test_server.py::TestSignalHandling, test_validate_cycle3.py::TestSigtermFunctionalBehavior | Raises SystemExit(0), sets events |
| Signal handling (SIGUSR1) | YES | test_server.py::TestSignalHandling::test_sigusr1_sets_wake_not_shutdown | Wake without shutdown |
| _org_uuid instance state (TS-13) | YES | test_validate_cycle3.py::TestOrgUuidInstanceLifecycleThroughDoScrape, TestOrgUuidInstanceIsolation | Full lifecycle, isolation, error recovery |
| Error signaling ("X" utilization) | YES | test_server.py::TestRendererNoneUtilizationGuard, test_validate_gaps.py::TestErrorBridge* | Error bridge immutability, sanitization |
| Atomic writes | YES | test_validate_gaps.py::TestClientFetchQuotaAtomicWrite | No tmp file after success, creates parent dirs |
| Deployment files (Dockerfile) | YES | test_deploy.py | Dockerfile, systemd unit, launchd plist |
| Package structure | YES | test_package.py | Entry points, imports, __main__ guard |
| Install/uninstall scripts | NO | — | Shell scripts not unit tested (integration-level concern) |
| QUOTA_DATA_PATH backward compat | NO | — | Renderer setting honored but untested |

## Tests Written This Step
- `server/tests/test_validate_cycle3.py` (47 tests): Covers ESCALATE cycle 3 gaps:
  - **TS-13 _org_uuid lifecycle** (8 tests): Instance initialization, caching across scrape cycles, auth error clearing, rediscovery, rate limit preservation, key file error resilience, exception resilience, instance isolation
  - **TS-22 SIGTERM** (4 tests): Raises SystemExit(0), same for SIGINT, shutdown events set before exception, poll loop exits on shutdown
  - **WSGI Content-Type** (4 tests): JSON content type on /quota, /health, 503, 404
  - **WSGI response contract** (3 tests): Success JSON structure, 503 error field, error status passthrough
  - **Data integrity** (2 tests): Error bridge from key error and exception contains no org_uuid
  - **Client edge cases** (5 tests): Timeout handling (3s), malformed URLs, None URL, large 100KB payload
  - **Security injection** (8 tests): SQL injection, XSS, command injection, null bytes, path traversal in session key; error bridge sanitization; adversarial status values
  - **Symlink handling** (2 tests): Valid symlink to key file, dangling symlink
  - **Config boundaries** (5 tests): Port 0, port 65535, interval 0, interval 1, negative port
  - **Exception preservation** (1 test): _do_scrape exception replaces stale success with error bridge
  - **Health contract** (4 tests): ok/degraded/error states, uptime increasing
  - **Error bridge no-leak** (1 test): Error bridge never contains org_uuid

## Strengths

- **Test quality is exceptionally high**: 362 tests with zero failures, covering unit, integration (WSGI), security edge cases, and cross-module boundaries. The polyglot extraction harness (TS-23) is particularly clever — it tests real embedded code rather than re-implementations.

- **Security testing is thorough**: Auth bypass regression tests, empty key exploitation, null byte injection, timing-safe comparison verification, session key injection patterns, and data leakage checks.

- **Error path coverage is comprehensive**: Every error status in the scraper's status_map has corresponding test coverage. Exception paths in _do_scrape are tested for both cached data updates and _org_uuid preservation.

- **Instance isolation verified**: The TS-13 refactor is validated by a test that proves two QuotaServer instances have independent _org_uuid state — the exact bug the fix addressed.
