# Validation Report

## Summary
- Tests before validation: 235 total (235 passing, 0 failing)
- Tests after validation: 292 total (292 passing, 0 failing)
- Requirements coverage: 11/13 requirements have tests (2 require manual/infra testing)
- Mock audit: All mocks target external dependencies (curl_cffi HTTP, scraper functions called by server) -- acceptable usage pattern
- New test file: `server/tests/test_validate_gaps.py` (57 tests)

## Coverage Map

| Requirement | Test File | Status |
|-------------|-----------|--------|
| Server scrapes claude.ai for quota | test_scraper.py:TestFetchQuota | covered |
| GET /quota returns bridge JSON format | test_server.py:TestQuotaEndpoint, TestQuotaBridgeFormatContract | covered |
| GET /health for monitoring | test_server.py:TestHealthEndpoint | covered |
| Optional API key auth via hmac.compare_digest | test_server.py:TestAuthHook, test_validate_gaps.py:TestAuthSecurityEdgeCases | covered |
| Client fetches from QUOTA_SOURCE URL | test_validate_gaps.py:TestClientFetchQuotaHappyPath | covered (NEW) |
| Client caches to disk with TTL | test_validate_gaps.py:TestClientFetchQuotaCacheTTL | covered (NEW) |
| Silent failure with stale cache fallback | test_validate_gaps.py:TestClientFetchQuotaSilentFailure | covered (NEW) |
| Atomic writes for cache files | test_validate_gaps.py:TestClientFetchQuotaAtomicWrite | covered (NEW) |
| Standalone mode (no QUOTA_SOURCE) unchanged | test_validate_gaps.py:TestClientFetchQuotaSilentFailure::test_no_op_when_source_url_empty | covered (NEW) |
| Error signaling with "X" utilization values | test_scraper.py:TestErrorBridge, test_server.py:TestQuotaBridgeFormatContract | covered |
| Server installable independently | test_package.py:TestPyprojectToml, TestModuleRunnable | covered |
| Server deployable via Docker | test_deploy.py:TestDockerfile* | covered (static, no build) |
| Server deployable via systemd/launchd | test_deploy.py:TestSystemd*, TestLaunchd* | covered (static) |

## Tests Written

### Client Integration (NEW)
| Test | File | What it verifies |
|------|------|-----------------|
| test_fetches_and_writes_cache_file | test_validate_gaps.py:TestClientFetchQuotaHappyPath | HTTP fetch writes valid JSON cache |
| test_appends_quota_to_url | test_validate_gaps.py:TestClientFetchQuotaHappyPath | /quota appended to base URL |
| test_appends_quota_to_url_with_trailing_slash | test_validate_gaps.py:TestClientFetchQuotaHappyPath | Trailing slash handled |
| test_sends_api_key_header_when_configured | test_validate_gaps.py:TestClientFetchQuotaHappyPath | X-API-Key header sent |
| test_no_api_key_header_when_empty | test_validate_gaps.py:TestClientFetchQuotaHappyPath | No header when key empty |
| test_skips_fetch_when_cache_is_fresh | test_validate_gaps.py:TestClientFetchQuotaCacheTTL | TTL prevents redundant fetch |
| test_fetches_when_cache_is_stale | test_validate_gaps.py:TestClientFetchQuotaCacheTTL | Stale cache triggers fetch |
| test_fetches_when_no_cache_file | test_validate_gaps.py:TestClientFetchQuotaCacheTTL | Missing cache triggers fetch |
| test_ttl_zero_always_fetches | test_validate_gaps.py:TestClientFetchQuotaCacheTTL | TTL=0 disables caching |
| test_no_op_when_source_url_empty | test_validate_gaps.py:TestClientFetchQuotaSilentFailure | Empty URL is no-op |
| test_no_op_when_source_url_none_like | test_validate_gaps.py:TestClientFetchQuotaSilentFailure | Falsy URL is no-op |
| test_silent_failure_on_connection_refused | test_validate_gaps.py:TestClientFetchQuotaSilentFailure | No exception on conn refused |
| test_silent_failure_on_server_error | test_validate_gaps.py:TestClientFetchQuotaSilentFailure | No exception on HTTP 500 |
| test_silent_failure_on_invalid_json_response | test_validate_gaps.py:TestClientFetchQuotaSilentFailure | Invalid JSON not written |
| test_preserves_stale_cache_on_failure | test_validate_gaps.py:TestClientFetchQuotaSilentFailure | Stale cache survives failure |
| test_no_tmp_file_after_success | test_validate_gaps.py:TestClientFetchQuotaAtomicWrite | No .tmp remnant |
| test_creates_parent_directories | test_validate_gaps.py:TestClientFetchQuotaAtomicWrite | Creates cache dir tree |

### Security (NEW)
| Test | File | What it verifies |
|------|------|-----------------|
| test_hmac_compare_digest_empty_strings_is_true | test_validate_gaps.py:TestEmptyApiKeySecurityFinding | Documents empty key bypass |
| test_empty_api_key_allows_empty_header_through | test_validate_gaps.py:TestEmptyApiKeySecurityFinding | Empty key file is auth bypass |
| test_auth_rejects_partial_key | test_validate_gaps.py:TestAuthSecurityEdgeCases | Partial key rejected |
| test_auth_rejects_key_with_extra_chars | test_validate_gaps.py:TestAuthSecurityEdgeCases | Extended key rejected |
| test_auth_rejects_case_different_key | test_validate_gaps.py:TestAuthSecurityEdgeCases | Case-sensitive comparison |
| test_auth_rejects_null_byte_injection | test_validate_gaps.py:TestAuthSecurityEdgeCases | Null byte injection rejected |
| test_auth_401_response_is_json | test_validate_gaps.py:TestAuthSecurityEdgeCases | 401 body is valid JSON |
| test_auth_does_not_leak_expected_key | test_validate_gaps.py:TestAuthSecurityEdgeCases | Expected key not in response |

### Error Path Coverage (NEW)
| Test | File | What it verifies |
|------|------|-----------------|
| test_insecure_permissions_error | test_validate_gaps.py:TestDoScrapeAllKeyErrors | insecure_permissions key error |
| test_invalid_json_error | test_validate_gaps.py:TestDoScrapeAllKeyErrors | invalid_json key error |
| test_import_error_returns_upstream_error | test_validate_gaps.py:TestFetchQuotaImportError | curl_cffi ImportError path |

### Edge Cases (NEW)
| Test | File | What it verifies |
|------|------|-----------------|
| test_session_key_with_unicode_chars | test_validate_gaps.py:TestReadSessionKeyUnicode | Unicode in key value |
| test_empty_json_object | test_validate_gaps.py:TestReadSessionKeyUnicode | Empty JSON object |
| test_null_session_key_value | test_validate_gaps.py:TestReadSessionKeyUnicode | null sessionKey value |
| test_empty_string_session_key | test_validate_gaps.py:TestReadSessionKeyUnicode | Empty string key |
| test_empty_file | test_validate_gaps.py:TestReadSessionKeyUnicode | Empty file content |
| test_json_with_extra_fields | test_validate_gaps.py:TestReadSessionKeyUnicode | Extra JSON fields ignored |
| test_empty_usage_response | test_validate_gaps.py:TestFetchQuotaMissingWindowKeys | Empty usage body |
| test_partial_window_data | test_validate_gaps.py:TestFetchQuotaMissingWindowKeys | Missing resets_at |
| test_window_value_is_none | test_validate_gaps.py:TestFetchQuotaMissingWindowKeys | None window value |
| test_separate_calls_return_different_objects | test_validate_gaps.py:TestErrorBridgeImmutability | No object reuse |
| test_mutating_result_does_not_affect_next_call | test_validate_gaps.py:TestErrorBridgeImmutability | No shared state |
| test_repeated_requests_same_data | test_validate_gaps.py:TestQuotaEndpointConsistency | Read consistency |
| test_data_update_reflected_immediately | test_validate_gaps.py:TestQuotaEndpointConsistency | Write visibility |

### Config Validation (NEW)
| Test | File | What it verifies |
|------|------|-----------------|
| test_unknown_flag_rejected | test_validate_gaps.py:TestConfigUnknownArgs | Unknown args rejected |
| test_unknown_short_flag_rejected | test_validate_gaps.py:TestConfigUnknownArgs | Unknown short flags rejected |
| test_invalid_port_type_rejected | test_validate_gaps.py:TestConfigUnknownArgs | Non-int port rejected |
| test_invalid_interval_type_rejected | test_validate_gaps.py:TestConfigUnknownArgs | Non-int interval rejected |
| test_warning_on_ipv6_all_interfaces | test_validate_gaps.py:TestWarnIfExposedExtendedHosts | :: triggers warning |
| test_warning_on_public_ip | test_validate_gaps.py:TestWarnIfExposedExtendedHosts | Public IP triggers warning |

### Structural Verification (NEW)
| Test | File | What it verifies |
|------|------|-----------------|
| test_cookie_header_format_in_source | test_validate_gaps.py:TestHttpGetHeaders | Cookie format string |
| test_request_headers_included_in_http_get | test_validate_gaps.py:TestHttpGetHeaders | Headers merged correctly |
| test_impersonate_chrome_in_source | test_validate_gaps.py:TestHttpGetHeaders | Chrome TLS impersonation |
| test_timeout_set_in_source | test_validate_gaps.py:TestHttpGetHeaders | HTTP timeout configured |
| test_quiet_true_passed_to_bottle_run | test_validate_gaps.py:TestBottleQuietMode | Bottle suppresses output |
| test_scraper_error_bridge_imported_in_server | test_validate_gaps.py:TestServerUsesScraperErrorBridge | Server uses shared error bridge |
| test_error_bridge_output_is_json_serializable | test_validate_gaps.py:TestServerUsesScraperErrorBridge | JSON serialization safe |

## Mock Audit

| Test Area | Mock Target | Verdict | Action |
|-----------|-------------|---------|--------|
| TestFetchQuota* | scraper._http_get | acceptable | Mocks external HTTP to claude.ai |
| TestOrgUuidCaching | scraper._http_get | acceptable | Mocks external HTTP to claude.ai |
| TestOrgUuidResetOnAuthError | scraper._http_get | acceptable | Mocks external HTTP to claude.ai |
| TestBackgroundPollThread | scraper.read_session_key, fetch_quota | acceptable | Mocks file I/O and external HTTP |
| TestServerRun | signal.signal, _poll_loop | acceptable | Mocks OS signals and background thread |
| TestMainFunction | parse_args, QuotaServer, logging | acceptable | Mocks orchestration to avoid starting real server |
| TestMainModuleMain | __main__._server_main | acceptable | Mocks to avoid starting real server |
| TestQuotaServer* | bottle module | acceptable | Mocks bottle web framework (external dependency) |
| NEW: TestClientFetch* | None | no mocks | Uses real HTTP server (http.server.HTTPServer) |

All mocks target external services (curl_cffi HTTP, bottle web framework) or OS-level operations (signal handlers, file I/O for session keys). No test mocks the system under test. The client integration tests use a real in-process HTTP server instead of mocking urllib.

## Findings

### FINDING-1: Empty API Key File Creates Auth Bypass
- **Severity**: Critical
- **Description**: When `--api-key-file` points to an empty or whitespace-only file, `_load_api_key()` returns `""` (empty string). The auth hook then calls `hmac.compare_digest("", provided)` -- if an attacker sends an empty `X-API-Key: ""` header, this returns `True`, bypassing authentication entirely.
- **Test**: `TestEmptyApiKeySecurityFinding::test_empty_api_key_allows_empty_header_through`
- **Option A**: In `_load_api_key()`, return `None` instead of `""` when the stripped key is empty. Pro: Simple fix, auth disabled when no real key. Con: Operator may not realize auth is disabled.
- **Option B**: In `_load_api_key()`, log an error and exit if the key file exists but is empty. Pro: Fail-fast, operator notices immediately. Con: Breaks startup if key file is accidentally emptied.
- **Recommendation**: Option A (return None for empty keys) + log a WARNING about disabled auth.

### FINDING-2: Client _maybe_fetch_quota is Embedded in Shell Script
- **Severity**: Important
- **Description**: The `_maybe_fetch_quota` function is embedded inline in the `scripts/tmux-claude-status` bash/python polyglot script. It cannot be imported and tested directly. The validation tests re-implement the function to verify its logic. Any drift between the real script and the test re-implementation would not be caught.
- **Option A**: Extract `_maybe_fetch_quota` into a standalone Python module importable by tests. Pro: Direct testing, no drift risk. Con: Adds a file, changes the script structure.
- **Option B**: Keep the re-implementation approach but add a hash-based check that the source function matches. Pro: No structural change. Con: Fragile, breaks on whitespace changes.
- **Recommendation**: Option A -- extract to a shared module.

### FINDING-3: Scraper Module-Level _org_uuid Global State (Known: TS-13)
- **Severity**: Important (already tracked as TS-13)
- **Description**: The `_org_uuid` module-level variable makes the scraper module stateful. Tests must manually reset `scraper._org_uuid = None` in setUp(). This is already tracked as TS-13 and is not a new finding.

## Gaps Remaining

1. **Docker build test**: Dockerfile content is tested statically but no test actually builds the Docker image. Requires Docker daemon access.
2. **End-to-end integration test**: No test starts the full server (QuotaServer.run()) and makes real HTTP requests against it. This would require a test that starts the server in a subprocess and validates /quota and /health endpoints with real networking. Blocked by needing to mock curl_cffi for the scraper backend.
3. **Client script full integration**: The re-implemented `_maybe_fetch_quota` tests verify the logic but do not exercise the actual script code path. See FINDING-2.
4. **Load/performance testing**: No benchmark tests exist for the server. Given this is a single-user status bar tool, this is low priority.

## Recommendations

1. **P0**: Fix the empty API key bypass (FINDING-1). Create a story for `_load_api_key` to return None when the key file is empty/whitespace-only.
2. **P1**: Extract `_maybe_fetch_quota` from the embedded script into a testable Python module (FINDING-2).
3. **P2**: Add an integration test that starts QuotaServer in a subprocess and validates real HTTP round-trips for /quota, /health, and auth rejection.
4. **P3**: Consider adding a conftest.py with shared fixtures (tmpdir for key files, mock bottle helper) to reduce boilerplate across test files.
