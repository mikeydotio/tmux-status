# Review Report

## Summary

The tmux-status codebase is well-structured with strong test coverage (315 passing tests), solid security fundamentals (timing-safe auth, session key permission checks, atomic writes), and clean separation between server and client components. However, a critical status code mismatch between the new server and the renderer means error conditions like expired session keys do not trigger the red color indicator in the status bar -- a functional regression from the pre-server architecture. Two additional important findings affect the Dockerfile security posture and a code injection surface in the polyglot script.

## Findings

### Status Code Mismatch: Server "session_key_expired" vs Renderer "expired"
- **Severity**: Critical
- **Description**: The new server scraper (`scraper.py:117`) maps HTTP 401 to status `"session_key_expired"`, but the renderer (`tmux-claude-status:298`) checks for `"expired"` in its bash case pattern to trigger the red error color. The old deprecated `tmux-status-quota-fetch:166` used `"expired"` which matched the renderer. With the new server, a 401 from claude.ai produces `status: "session_key_expired"` in the `/quota` response, which flows through the client cache to the renderer, where it falls through the case pattern without matching. The user sees default-color text instead of red, missing the visual signal that their session key needs renewal.
- **Location**: `server/tmux_status_server/scraper.py:117` (status_map definition) and `scripts/tmux-claude-status:298` (case pattern)
- **Option 1 (Recommended)**: Update the renderer's case pattern at line 298 to include `session_key_expired` alongside `expired`: `expired|session_key_expired|blocked|error|rate_limited|key_expired)`. -- Pros: backward-compatible with old bridge files, no server change. Cons: case pattern grows longer.
- **Option 2**: Change the server status_map in `scraper.py:117` to use `"expired"` instead of `"session_key_expired"` for HTTP 401, matching the old convention. -- Pros: shorter renderer pattern, matches DESIGN.md table which says `"expired"`. Cons: loses descriptive status code, requires updating all server tests that assert `"session_key_expired"`.

### Dockerfile Runs as Root
- **Severity**: Critical
- **Description**: The `server/Dockerfile` has no `USER` directive, so the `tmux-status-server` process runs as root inside the container. If the Bottle web server has a vulnerability (e.g., request parsing, header injection), an attacker gains root-level access within the container. The container also binds to `0.0.0.0` via the `CMD` default, compounding the exposure.
- **Location**: `server/Dockerfile:12-13`
- **Option 1 (Recommended)**: Add a non-root user and switch to it before the ENTRYPOINT: `RUN useradd -r -s /usr/sbin/nologin appuser` then `USER appuser`. -- Pros: defense-in-depth, follows container security best practices. Cons: minor Dockerfile complexity increase.
- **Option 2**: Add a `HEALTHCHECK` instruction and document that the container should be run with `--user` flag by the operator. -- Pros: no Dockerfile change. Cons: relies on operator discipline, less secure by default.

### Shell Injection via Filename in Polyglot Script
- **Severity**: Important
- **Description**: In `tmux-claude-status:22`, the bash variable `$pidfile` is interpolated directly into a Python string literal: `python3 -c "import json; print(json.load(open('$pidfile'))['pid'])"`. The `$pidfile` comes from a glob expansion of `~/.claude/sessions/*.json`. If a Claude session file has a name containing a single quote (e.g., created by a malicious process), the Python command breaks out of the string and executes arbitrary code. While exploitation requires write access to `~/.claude/sessions/` (which implies the attacker already has the user's privileges), this is still a code quality concern and a pattern to avoid.
- **Location**: `scripts/tmux-claude-status:22` and `:27`
- **Option 1 (Recommended)**: Pass the filename via an environment variable or argument instead of string interpolation: `python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['pid'])" "$pidfile"`. -- Pros: eliminates injection surface entirely. Cons: slight syntax change.
- **Option 2**: Use bash-native `jq` for JSON parsing instead of python3 inline: `pid=$(jq -r '.pid' "$pidfile" 2>/dev/null)`. -- Pros: simpler, faster, no injection risk. Cons: adds `jq` as a dependency (not currently required).

### Context Hook Uses Non-Atomic writeFileSync
- **Severity**: Important
- **Description**: The context hook (`tmux-status-context-hook.js:55`) writes the bridge file using `fs.writeFileSync()` directly to the final path, rather than writing to a temp file and renaming. The rest of the codebase (server cache writes, client quota cache, old fetch script) consistently uses the temp+rename atomic write pattern. If the renderer reads the file mid-write (every 5s via tmux status-interval), it could get a truncated JSON payload. In practice, this is unlikely to cause visible issues because the writes are small and fast, but it violates the project's stated "atomic writes everywhere" convention.
- **Location**: `scripts/tmux-status-context-hook.js:55`
- **Option 1 (Recommended)**: Write to `bridgePath + '.tmp'` then `fs.renameSync(tmpPath, bridgePath)`. -- Pros: matches the atomic write convention documented in CLAUDE.md and DESIGN.md. Cons: 2 extra lines of code.
- **Option 2**: Accept the inconsistency and document it as a known exception. The context hook is called frequently and the data payload is small (<100 bytes), so partial reads are extremely unlikely. -- Pros: no code change. Cons: inconsistent convention.

### Legacy Scripts Still Shipped and Symlinked
- **Severity**: Important
- **Description**: `tmux-status-quota-fetch` and `tmux-status-quota-poll` are described as deprecated in DESIGN.md ("scraping logic... moves to scraper.py", "Deprecated. Replaced by server's poll thread"), but `install.sh:22` still symlinks both scripts into `~/.local/bin/`, and `uninstall.sh:20` still manages them. The install script even kills old `tmux-status-quota-poll` processes (line 240-244), acknowledging they're replaced, but then symlinks the scripts anyway. Users could be confused about which system is active.
- **Location**: `install.sh:22` (SCRIPTS array), `scripts/tmux-status-quota-fetch` and `scripts/tmux-status-quota-poll`
- **Option 1 (Recommended)**: Remove the two deprecated scripts from the `SCRIPTS` array in `install.sh` so they are no longer symlinked on fresh installs. Keep the files in the repo for backward compatibility but don't actively deploy them. -- Pros: clean install experience, no user confusion. Cons: existing users who upgrade may still have old symlinks (the uninstaller handles this).
- **Option 2**: Add deprecation warnings at the top of both scripts that print once on first execution, informing the user to use the server instead. -- Pros: gentle migration. Cons: more code to maintain for deprecated scripts.

### Old Fetch Script Exposes Raw Exception Text in Bridge File
- **Severity**: Important
- **Description**: The deprecated `tmux-status-quota-fetch:278` catches generic exceptions and writes `str(e)` directly into the bridge file's `error` field. The new server scraper carefully avoids this (using only machine-readable codes like `"upstream_error"`), but since the old script is still shipped and could be invoked independently, it can expose internal exception details (file paths, network errors, Python tracebacks) into the JSON cache file. This could leak system information.
- **Location**: `scripts/tmux-status-quota-fetch:279`
- **Option 1 (Recommended)**: Replace `"error": str(e)` with `"error": "fetch_error"` to match the server's pattern of machine-readable error codes. -- Pros: consistent error handling, no information leakage. Cons: harder to debug errors from this script.
- **Option 2**: Since the script is deprecated, mark it clearly and do not symlink it (see finding above). If it's not deployed, the issue is moot. -- Pros: no code change to deprecated file. Cons: doesn't fix the issue if someone runs it manually.

### No Interval Validation in Server Config
- **Severity**: Useful
- **Description**: The `--interval` CLI argument accepts any integer, including 0 and negative values. An interval of 0 would cause the poll loop to scrape continuously in a tight loop (limited only by the scrape duration), potentially hammering claude.ai and getting rate-limited or blocked. The config module validates log levels via `choices` but does not validate the interval range.
- **Location**: `server/tmux_status_server/config.py:56-59`
- **Option 1 (Recommended)**: Add validation in `parse_args()` after parsing: `if args.interval < 30: parser.error("--interval must be >= 30")`. -- Pros: prevents accidental DoS of upstream, consistent with the old `MIN_INTERVAL = 30` in `tmux-status-quota-poll`. Cons: minor code addition.
- **Option 2**: Validate in `QuotaServer.__init__` by clamping: `self.interval = max(30, interval)`. -- Pros: defense at the usage site. Cons: silently changes user input, which may surprise the operator.

### Duplicate Scraping Logic Between Server and Legacy Script
- **Severity**: Useful
- **Description**: The request headers, org discovery flow, and usage extraction logic are duplicated between `server/tmux_status_server/scraper.py` and `scripts/tmux-status-quota-fetch`. Both define `REQUEST_HEADERS` with the same values, both implement `http_get()` with the same curl_cffi pattern, and both implement org UUID caching. DESIGN.md explicitly states the server "is the canonical owner of all scraping logic" and the old scripts are "deprecated". This duplication creates a maintenance burden and divergence risk (as evidenced by the status code mismatch found above).
- **Location**: `server/tmux_status_server/scraper.py` (canonical) vs `scripts/tmux-status-quota-fetch` (deprecated duplicate)
- **Option 1 (Recommended)**: Accept the duplication as a transitional state. The old scripts are deprecated and will be removed in a future cleanup. Document this in CLAUDE.md. -- Pros: no risk of breaking existing users. Cons: maintenance overhead until removal.
- **Option 2**: Remove the old scripts from the repository entirely. -- Pros: eliminates duplication and confusion. Cons: breaks users who haven't migrated yet, more aggressive than necessary.

### QUOTA_API_KEY Stored in Plaintext in settings.conf
- **Severity**: Useful
- **Description**: The client-side API key for authenticating with the quota server is stored as plaintext `QUOTA_API_KEY=...` in `settings.conf`. The server side uses `--api-key-file` with a dedicated file that can have restricted permissions (0600). The client side lacks a corresponding `QUOTA_API_KEY_FILE` option. This was previously escalated and accepted (TS-11) as the key only protects access to quota utilization data, not upstream credentials.
- **Location**: `scripts/tmux-claude-status:135` (reads QUOTA_API_KEY), `config/settings.example.conf:25`
- **Option 1**: Accept as-is per the TS-11 decision. The API key protects only quota percentages, not session credentials. Document the trade-off in the README. -- Pros: no code change, already reviewed. Cons: inconsistent security model between server and client.
- **Option 2**: Add a `QUOTA_API_KEY_FILE` directive that reads the key from a permission-restricted file, mirroring the server's approach. -- Pros: consistent, more secure. Cons: adds config complexity for a low-risk credential.

## Design Alignment

**MINOR DRIFT** -- The implementation closely follows the DESIGN.md architecture with one notable drift:

1. **Status code naming convention**: DESIGN.md error table shows `"expired"` for session key expiration, but the server implementation uses `"session_key_expired"`. This causes a functional mismatch with the renderer (see Critical finding above).

2. **Deprecated scripts still deployed**: DESIGN.md says old scripts are "Deprecated. Logic moves to scraper.py" and "Deprecated. Replaced by server's poll thread", but `install.sh` still symlinks them.

3. **Context hook atomic writes**: DESIGN.md specifies "Atomic writes everywhere (temp + rename)" but the Node.js context hook uses direct `writeFileSync`.

All other aspects align well: the REST API shape matches the spec, authentication uses `hmac.compare_digest()` in a `before_request` hook as specified, `/health` is exempt from auth, the default bind is `127.0.0.1:7850`, the client uses `urllib.request` with 3s timeout, error signaling uses "X" utilization values, and the server owns all scraping logic.

## Strengths

- **Comprehensive test coverage**: 315 tests cover the server package thoroughly, including unit tests, integration tests with real HTTP servers, security edge cases (null byte injection, timing-safe auth, empty key bypass), deployment file validation, and a clever polyglot extraction harness for testing embedded Python.

- **Security-first design**: Session key files require 0600 permissions, `hmac.compare_digest()` prevents timing attacks, error responses never leak raw exception text, default bind is localhost-only with a warning on non-localhost without auth, and the `.gitignore` properly excludes credential files.

- **Clean module boundaries**: `config.py` (stdlib only), `scraper.py` (only curl_cffi external dep), `server.py` (lazy Bottle import) -- each module has a clear responsibility and minimal dependency surface.

- **Graceful degradation**: The renderer silently falls back to stale cache, the server returns "X" utilization on errors providing a visual signal, the `/health` endpoint enables debugging, and the renderer produces no output when Claude is not running.

- **Atomic write discipline**: The server, client fetch function, and old fetch script all use temp+rename for cache writes, preventing partial reads during concurrent access.

- **Well-structured signal handling**: The SIGTERM fix (TS-22) correctly raises `SystemExit(0)` to propagate through Bottle's `serve_forever()`, and SIGUSR1 provides operational flexibility for on-demand scrapes.

## Dimensional Coverage

| Dimension | Status | Key Findings |
|-----------|--------|-------------|
| Architecture | reviewed | 3 findings: status code mismatch (Critical), deprecated scripts still deployed, duplicate scraping logic |
| Security | reviewed | 3 findings: Dockerfile runs as root (Critical), shell injection in polyglot script, plaintext API key (accepted) |
| Performance | reviewed | 0 findings: no algorithmic concerns; renderer runs in <100ms, server poll is I/O-bound with appropriate intervals |
| Test Coverage | reviewed | 0 findings: 315 tests passing, strong coverage including security edge cases and integration tests |
| API Consistency | reviewed | 1 finding: status code naming inconsistency between server and renderer (reported under Architecture) |
| Observability | reviewed | 0 findings: structured logging with configurable levels, /health endpoint for monitoring, clear error codes |
| User-Facing Text | reviewed | 0 findings: CLI help text is clear and concise, error messages are actionable, no LLM tells detected |
| License Compliance | reviewed | 0 findings: MIT project license, Bottle is MIT, curl_cffi is MIT. No copyleft risk. |

## Overall Assessment

**PROCEED WITH CHANGES**

The codebase is well-engineered with strong fundamentals in security, testing, and architecture. The critical status code mismatch is the only finding that affects end-user functionality and is a simple fix (either in the renderer's case pattern or the server's status_map). The Dockerfile root user issue should be addressed before any Docker deployment. The remaining findings are quality improvements that can be addressed incrementally.
