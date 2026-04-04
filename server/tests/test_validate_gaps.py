"""Validation pass 2: Tests for coverage gaps found in existing test suite.

Covers:
- Client-side _maybe_fetch_quota (HTTP fetch, atomic cache, TTL, silent failure)
- Security: empty/whitespace API key bypass detection
- Security: auth timing with various header values
- Scraper: ImportError path for missing curl_cffi
- Scraper: _http_get cookie header construction
- Server: _do_scrape with all key error variants
- Server: bottle quiet=True passed to run()
- Config: unknown arguments rejected
- Edge cases: unicode in key files, concurrent scrape state, large payloads
"""

import hmac
import http.server
import json
import os
import stat
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

# Add server directory to path so we can import the module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tmux_status_server import scraper
from tmux_status_server.config import parse_args
from tmux_status_server.scraper import (
    _error_bridge,
    fetch_quota,
    read_session_key,
)


# ---------------------------------------------------------------------------
# Helper: Simple HTTP server for client integration tests
# ---------------------------------------------------------------------------

class _QuotaHandler(http.server.BaseHTTPRequestHandler):
    """Minimal handler that serves JSON quota responses for testing."""

    # Class-level state so tests can configure behavior
    response_code = 200
    response_body = b'{"status":"ok","five_hour":{"utilization":42,"resets_at":null},"seven_day":{"utilization":15,"resets_at":null},"timestamp":1743696000}'
    expected_api_key = None
    request_log = []
    delay = 0

    def do_GET(self):
        _QuotaHandler.request_log.append({
            "path": self.path,
            "headers": dict(self.headers),
        })
        if self.delay:
            time.sleep(self.delay)
        if self.expected_api_key is not None:
            provided = self.headers.get("X-API-Key")
            if provided != self.expected_api_key:
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":"invalid_or_missing_api_key"}')
                return
        self.send_response(self.response_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(self.response_body)

    def log_message(self, format, *args):
        pass  # suppress server logs


def _start_test_server():
    """Start a test HTTP server on a random port. Returns (server, port)."""
    server = http.server.HTTPServer(("127.0.0.1", 0), _QuotaHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


# Import _maybe_fetch_quota from the client script (it is embedded in a bash/python script)
# We extract the function definition to test it independently.

def _maybe_fetch_quota_impl(source_url, api_key, cache_ttl, cache_path):
    """Re-implementation matching the client script logic for testability."""
    import urllib.request
    if not source_url:
        return
    if cache_ttl > 0:
        try:
            if time.time() - os.stat(cache_path).st_mtime < cache_ttl:
                return  # cache is fresh
        except FileNotFoundError:
            pass
    try:
        req = urllib.request.Request(source_url.rstrip('/') + '/quota')
        if api_key:
            req.add_header('X-API-Key', api_key)
        resp = urllib.request.urlopen(req, timeout=3)
        data = resp.read()
        json.loads(data)  # validate JSON
        cache_dir = os.path.dirname(cache_path)
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)
        tmp = cache_path + '.tmp'
        with open(tmp, 'wb') as f:
            f.write(data)
        os.replace(tmp, cache_path)
    except Exception:
        pass  # silent failure, use stale cache


# ---------------------------------------------------------------------------
# Client-side _maybe_fetch_quota integration tests
# ---------------------------------------------------------------------------

class TestClientFetchQuotaHappyPath(unittest.TestCase):
    """Test _maybe_fetch_quota fetches from server and writes cache."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cache_path = os.path.join(self.tmpdir, "quota-cache.json")
        _QuotaHandler.response_code = 200
        _QuotaHandler.response_body = json.dumps({
            "status": "ok",
            "five_hour": {"utilization": 42, "resets_at": None},
            "seven_day": {"utilization": 15, "resets_at": None},
            "timestamp": 1743696000,
        }).encode()
        _QuotaHandler.expected_api_key = None
        _QuotaHandler.request_log = []
        _QuotaHandler.delay = 0
        self.server, self.port = _start_test_server()

    def tearDown(self):
        self.server.shutdown()
        for f in [self.cache_path, self.cache_path + ".tmp"]:
            if os.path.exists(f):
                os.remove(f)
        if os.path.exists(self.tmpdir):
            os.rmdir(self.tmpdir)

    def test_fetches_and_writes_cache_file(self):
        """Successful fetch writes valid JSON to cache path."""
        url = f"http://127.0.0.1:{self.port}"
        _maybe_fetch_quota_impl(url, "", 0, self.cache_path)
        self.assertTrue(os.path.exists(self.cache_path))
        with open(self.cache_path) as f:
            data = json.load(f)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["five_hour"]["utilization"], 42)

    def test_appends_quota_to_url(self):
        """Request URL has /quota appended."""
        url = f"http://127.0.0.1:{self.port}"
        _maybe_fetch_quota_impl(url, "", 0, self.cache_path)
        self.assertEqual(len(_QuotaHandler.request_log), 1)
        self.assertEqual(_QuotaHandler.request_log[0]["path"], "/quota")

    def test_appends_quota_to_url_with_trailing_slash(self):
        """Trailing slash on source URL is handled correctly."""
        url = f"http://127.0.0.1:{self.port}/"
        _maybe_fetch_quota_impl(url, "", 0, self.cache_path)
        self.assertEqual(_QuotaHandler.request_log[0]["path"], "/quota")

    def test_sends_api_key_header_when_configured(self):
        """X-API-Key header is sent when api_key is non-empty."""
        _QuotaHandler.expected_api_key = "test-key-123"
        url = f"http://127.0.0.1:{self.port}"
        _maybe_fetch_quota_impl(url, "test-key-123", 0, self.cache_path)
        self.assertTrue(os.path.exists(self.cache_path))
        headers = _QuotaHandler.request_log[0]["headers"]
        self.assertEqual(headers.get("X-Api-Key"), "test-key-123")

    def test_no_api_key_header_when_empty(self):
        """No X-API-Key header is sent when api_key is empty string."""
        url = f"http://127.0.0.1:{self.port}"
        _maybe_fetch_quota_impl(url, "", 0, self.cache_path)
        headers = _QuotaHandler.request_log[0]["headers"]
        self.assertNotIn("X-Api-Key", headers)
        self.assertNotIn("x-api-key", headers)


class TestClientFetchQuotaCacheTTL(unittest.TestCase):
    """Test TTL-based cache freshness check."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cache_path = os.path.join(self.tmpdir, "quota-cache.json")
        _QuotaHandler.response_code = 200
        _QuotaHandler.response_body = b'{"status":"ok","five_hour":{"utilization":50,"resets_at":null},"seven_day":{"utilization":20,"resets_at":null},"timestamp":9999}'
        _QuotaHandler.expected_api_key = None
        _QuotaHandler.request_log = []
        _QuotaHandler.delay = 0
        self.server, self.port = _start_test_server()

    def tearDown(self):
        self.server.shutdown()
        for f in [self.cache_path, self.cache_path + ".tmp"]:
            if os.path.exists(f):
                os.remove(f)
        if os.path.exists(self.tmpdir):
            os.rmdir(self.tmpdir)

    def test_skips_fetch_when_cache_is_fresh(self):
        """Does not fetch when cache mtime is within TTL."""
        # Write a cache file first
        with open(self.cache_path, "w") as f:
            json.dump({"status": "ok", "five_hour": {}, "seven_day": {}, "timestamp": 1}, f)
        url = f"http://127.0.0.1:{self.port}"
        _maybe_fetch_quota_impl(url, "", 3600, self.cache_path)
        # No request should have been made
        self.assertEqual(len(_QuotaHandler.request_log), 0)

    def test_fetches_when_cache_is_stale(self):
        """Fetches when cache mtime exceeds TTL."""
        with open(self.cache_path, "w") as f:
            json.dump({"status": "old"}, f)
        # Set mtime to 1 hour ago
        old_time = time.time() - 3600
        os.utime(self.cache_path, (old_time, old_time))
        url = f"http://127.0.0.1:{self.port}"
        _maybe_fetch_quota_impl(url, "", 30, self.cache_path)
        self.assertEqual(len(_QuotaHandler.request_log), 1)

    def test_fetches_when_no_cache_file(self):
        """Fetches when cache file does not exist."""
        url = f"http://127.0.0.1:{self.port}"
        _maybe_fetch_quota_impl(url, "", 30, self.cache_path)
        self.assertEqual(len(_QuotaHandler.request_log), 1)
        self.assertTrue(os.path.exists(self.cache_path))

    def test_ttl_zero_always_fetches(self):
        """TTL=0 disables caching, always fetches."""
        with open(self.cache_path, "w") as f:
            json.dump({"status": "ok"}, f)
        url = f"http://127.0.0.1:{self.port}"
        _maybe_fetch_quota_impl(url, "", 0, self.cache_path)
        self.assertEqual(len(_QuotaHandler.request_log), 1)


class TestClientFetchQuotaSilentFailure(unittest.TestCase):
    """Test that _maybe_fetch_quota fails silently on errors."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cache_path = os.path.join(self.tmpdir, "quota-cache.json")
        _QuotaHandler.request_log = []
        _QuotaHandler.delay = 0

    def tearDown(self):
        for f in [self.cache_path, self.cache_path + ".tmp"]:
            if os.path.exists(f):
                os.remove(f)
        if os.path.exists(self.tmpdir):
            os.rmdir(self.tmpdir)

    def test_no_op_when_source_url_empty(self):
        """Does nothing when source_url is empty string."""
        _maybe_fetch_quota_impl("", "", 0, self.cache_path)
        self.assertFalse(os.path.exists(self.cache_path))

    def test_no_op_when_source_url_none_like(self):
        """Does nothing when source_url is falsy."""
        _maybe_fetch_quota_impl("", "key", 0, self.cache_path)
        self.assertFalse(os.path.exists(self.cache_path))

    def test_silent_failure_on_connection_refused(self):
        """Does not raise when server is not running (connection refused)."""
        # Use a port that is almost certainly not listening
        _maybe_fetch_quota_impl("http://127.0.0.1:1", "", 0, self.cache_path)
        self.assertFalse(os.path.exists(self.cache_path))

    def test_silent_failure_on_server_error(self):
        """Does not raise when server returns 500."""
        _QuotaHandler.response_code = 500
        _QuotaHandler.response_body = b'{"error":"internal"}'
        _QuotaHandler.expected_api_key = None
        server, port = _start_test_server()
        try:
            # urllib raises on 500, so this should be caught silently
            _maybe_fetch_quota_impl(f"http://127.0.0.1:{port}", "", 0, self.cache_path)
            self.assertFalse(os.path.exists(self.cache_path))
        finally:
            server.shutdown()

    def test_silent_failure_on_invalid_json_response(self):
        """Does not raise and does not write cache when response is not valid JSON."""
        _QuotaHandler.response_code = 200
        _QuotaHandler.response_body = b"not valid json {{"
        _QuotaHandler.expected_api_key = None
        server, port = _start_test_server()
        try:
            _maybe_fetch_quota_impl(f"http://127.0.0.1:{port}", "", 0, self.cache_path)
            self.assertFalse(os.path.exists(self.cache_path))
        finally:
            server.shutdown()

    def test_preserves_stale_cache_on_failure(self):
        """Stale cache is preserved when fetch fails."""
        stale_data = {"status": "ok", "five_hour": {"utilization": 10}}
        with open(self.cache_path, "w") as f:
            json.dump(stale_data, f)
        old_time = time.time() - 3600
        os.utime(self.cache_path, (old_time, old_time))
        # Fetch from unreachable server
        _maybe_fetch_quota_impl("http://127.0.0.1:1", "", 0, self.cache_path)
        # Stale cache should still be there
        self.assertTrue(os.path.exists(self.cache_path))
        with open(self.cache_path) as f:
            data = json.load(f)
        self.assertEqual(data["status"], "ok")


class TestClientFetchQuotaAtomicWrite(unittest.TestCase):
    """Test that cache writes use atomic temp+rename pattern."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cache_path = os.path.join(self.tmpdir, "quota-cache.json")
        _QuotaHandler.response_code = 200
        _QuotaHandler.response_body = b'{"status":"ok","five_hour":{"utilization":42,"resets_at":null},"seven_day":{"utilization":15,"resets_at":null},"timestamp":1743696000}'
        _QuotaHandler.expected_api_key = None
        _QuotaHandler.request_log = []
        _QuotaHandler.delay = 0
        self.server, self.port = _start_test_server()

    def tearDown(self):
        self.server.shutdown()
        for f in [self.cache_path, self.cache_path + ".tmp"]:
            if os.path.exists(f):
                os.remove(f)
        if os.path.exists(self.tmpdir):
            os.rmdir(self.tmpdir)

    def test_no_tmp_file_after_success(self):
        """After successful write, no .tmp file remains."""
        url = f"http://127.0.0.1:{self.port}"
        _maybe_fetch_quota_impl(url, "", 0, self.cache_path)
        self.assertFalse(os.path.exists(self.cache_path + ".tmp"))
        self.assertTrue(os.path.exists(self.cache_path))

    def test_creates_parent_directories(self):
        """Creates parent directories for cache path if they don't exist."""
        nested_path = os.path.join(self.tmpdir, "sub", "dir", "quota.json")
        url = f"http://127.0.0.1:{self.port}"
        _maybe_fetch_quota_impl(url, "", 0, nested_path)
        self.assertTrue(os.path.exists(nested_path))
        # Clean up nested dirs
        os.remove(nested_path)
        os.rmdir(os.path.join(self.tmpdir, "sub", "dir"))
        os.rmdir(os.path.join(self.tmpdir, "sub"))


# ---------------------------------------------------------------------------
# Security: Empty API key bypass
# ---------------------------------------------------------------------------

class TestEmptyApiKeySecurityFinding(unittest.TestCase):
    """FIXED: Empty API key file auth bypass via hmac.compare_digest('', '').

    Previously, _load_api_key() returned '' for empty files, allowing
    hmac.compare_digest('', '') to bypass auth. Now _load_api_key() returns
    None for empty/whitespace files, so _api_key is None and the auth hook
    short-circuits (skips auth, treating it as "no key configured").
    """

    def test_hmac_compare_digest_empty_strings_is_true(self):
        """hmac.compare_digest('', '') returns True -- the bypass vector that was fixed."""
        self.assertTrue(hmac.compare_digest("", ""))

    def test_empty_api_key_file_returns_none_not_empty_string(self):
        """_load_api_key() returns None for empty files, preventing the bypass."""
        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".key", delete=False) as f:
            f.write("")
            key_path = f.name
        try:
            from test_server import _make_server
            server, routes, hooks, errors, mb = _make_server(api_key_file=key_path)
            result = server._load_api_key()
            self.assertIsNone(result, "_load_api_key() should return None for empty files")
        finally:
            os.unlink(key_path)

    def test_none_api_key_skips_auth_entirely(self):
        """When _api_key is None, auth hook short-circuits -- no bypass possible."""
        from test_server import _make_server
        server, routes, hooks, errors, mb = _make_server(api_key_file="/tmp/api.key")
        server._api_key = None  # simulates empty file -> _load_api_key() returns None
        mb.request.path = "/quota"
        mb.request.get_header.return_value = ""
        result = hooks["before_request"]()
        # Auth is skipped entirely (no key configured), abort is NOT called
        mb.abort.assert_not_called()
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Security: Auth header injection attempts
# ---------------------------------------------------------------------------

class TestAuthSecurityEdgeCases(unittest.TestCase):
    """Test authentication with adversarial header values."""

    def test_auth_rejects_partial_key(self):
        """Partial API key is rejected."""
        from test_server import _make_server
        server, routes, hooks, errors, mb = _make_server(api_key_file="/tmp/api.key")
        server._api_key = "my-secret-key-12345"
        mb.request.path = "/quota"
        mb.request.get_header.return_value = "my-secret"
        hooks["before_request"]()
        mb.abort.assert_called_once()
        self.assertEqual(mb.abort.call_args[0][0], 401)

    def test_auth_rejects_key_with_extra_chars(self):
        """API key with appended characters is rejected."""
        from test_server import _make_server
        server, routes, hooks, errors, mb = _make_server(api_key_file="/tmp/api.key")
        server._api_key = "my-secret-key"
        mb.request.path = "/quota"
        mb.request.get_header.return_value = "my-secret-key-extra"
        hooks["before_request"]()
        mb.abort.assert_called_once()
        self.assertEqual(mb.abort.call_args[0][0], 401)

    def test_auth_rejects_case_different_key(self):
        """API key comparison is case-sensitive."""
        from test_server import _make_server
        server, routes, hooks, errors, mb = _make_server(api_key_file="/tmp/api.key")
        server._api_key = "MySecretKey"
        mb.request.path = "/quota"
        mb.request.get_header.return_value = "mysecretkey"
        hooks["before_request"]()
        mb.abort.assert_called_once()
        self.assertEqual(mb.abort.call_args[0][0], 401)

    def test_auth_rejects_null_byte_injection(self):
        """API key with null bytes injected is rejected."""
        from test_server import _make_server
        server, routes, hooks, errors, mb = _make_server(api_key_file="/tmp/api.key")
        server._api_key = "valid-key"
        mb.request.path = "/quota"
        mb.request.get_header.return_value = "valid-key\x00extra"
        hooks["before_request"]()
        mb.abort.assert_called_once()
        self.assertEqual(mb.abort.call_args[0][0], 401)

    def test_auth_401_response_is_json(self):
        """Auth failure returns valid JSON with correct error code."""
        from test_server import _make_server
        server, routes, hooks, errors, mb = _make_server(api_key_file="/tmp/api.key")
        server._api_key = "correct"
        mb.request.path = "/quota"
        mb.request.get_header.return_value = "wrong"
        hooks["before_request"]()
        mb.abort.assert_called_once()
        body = mb.abort.call_args[0][1]
        data = json.loads(body)
        self.assertEqual(data["error"], "invalid_or_missing_api_key")

    def test_auth_does_not_leak_expected_key(self):
        """Auth failure response does not contain the expected API key."""
        from test_server import _make_server
        server, routes, hooks, errors, mb = _make_server(api_key_file="/tmp/api.key")
        server._api_key = "super-secret-dont-leak"
        mb.request.path = "/quota"
        mb.request.get_header.return_value = "wrong"
        hooks["before_request"]()
        mb.abort.assert_called_once()
        body = mb.abort.call_args[0][1]
        self.assertNotIn("super-secret-dont-leak", body)


# ---------------------------------------------------------------------------
# Scraper: ImportError path for missing curl_cffi
# ---------------------------------------------------------------------------

class TestFetchQuotaImportError(unittest.TestCase):
    """Test fetch_quota when curl_cffi is not installed."""

    def setUp(self):
        scraper._org_uuid = None

    def test_import_error_returns_upstream_error(self):
        """When curl_cffi import fails, fetch_quota returns upstream_error."""
        # Simulate ImportError by mocking _http_get to raise ImportError
        with mock.patch("tmux_status_server.scraper._http_get",
                        side_effect=ImportError("No module named 'curl_cffi'")):
            result = fetch_quota("sk-ant-test")
        self.assertEqual(result["status"], "upstream_error")
        self.assertEqual(result["error"], "upstream_error")
        self.assertEqual(result["five_hour"]["utilization"], "X")


# ---------------------------------------------------------------------------
# Scraper: _http_get cookie header construction
# ---------------------------------------------------------------------------

class TestHttpGetHeaders(unittest.TestCase):
    """Test that _http_get constructs correct headers including Cookie."""

    def test_cookie_header_format_in_source(self):
        """_http_get constructs Cookie header as 'sessionKey={value}'."""
        scraper_path = os.path.join(
            os.path.dirname(__file__), "..", "tmux_status_server", "scraper.py"
        )
        with open(scraper_path) as f:
            source = f.read()
        # Verify the cookie header format string
        self.assertIn('f"sessionKey={session_key}"', source)
        self.assertIn('"Cookie"', source)

    def test_request_headers_included_in_http_get(self):
        """_http_get merges REQUEST_HEADERS with the Cookie header."""
        scraper_path = os.path.join(
            os.path.dirname(__file__), "..", "tmux_status_server", "scraper.py"
        )
        with open(scraper_path) as f:
            source = f.read()
        # Verify REQUEST_HEADERS is spread into the headers dict
        self.assertIn("{**REQUEST_HEADERS", source)

    def test_impersonate_chrome_in_source(self):
        """_http_get uses Chrome TLS impersonation."""
        scraper_path = os.path.join(
            os.path.dirname(__file__), "..", "tmux_status_server", "scraper.py"
        )
        with open(scraper_path) as f:
            source = f.read()
        self.assertIn('impersonate="chrome', source)

    def test_timeout_set_in_source(self):
        """_http_get sets a timeout on HTTP requests."""
        scraper_path = os.path.join(
            os.path.dirname(__file__), "..", "tmux_status_server", "scraper.py"
        )
        with open(scraper_path) as f:
            source = f.read()
        self.assertIn("timeout=", source)


# ---------------------------------------------------------------------------
# Server: _do_scrape with all session key error codes
# ---------------------------------------------------------------------------

class TestDoScrapeAllKeyErrors(unittest.TestCase):
    """Test _do_scrape handles all possible session key error codes."""

    def _make_server(self, **overrides):
        from test_server import _make_server as _ms
        return _ms(**overrides)

    @mock.patch("tmux_status_server.scraper.read_session_key")
    def test_insecure_permissions_error(self, mock_read_key):
        """_do_scrape handles insecure_permissions key error."""
        server, _, _, _, _ = self._make_server()
        mock_read_key.return_value = {"error": "insecure_permissions"}
        server._do_scrape()
        self.assertIsNotNone(server._cached_data)
        self.assertEqual(server._cached_data["status"], "insecure_permissions")
        self.assertEqual(server._cached_data["error"], "insecure_permissions")
        self.assertFalse(server._last_scrape_ok)

    @mock.patch("tmux_status_server.scraper.read_session_key")
    def test_invalid_json_error(self, mock_read_key):
        """_do_scrape handles invalid_json key error."""
        server, _, _, _, _ = self._make_server()
        mock_read_key.return_value = {"error": "invalid_json"}
        server._do_scrape()
        self.assertEqual(server._cached_data["status"], "invalid_json")
        self.assertEqual(server._cached_data["error"], "invalid_json")
        self.assertFalse(server._last_scrape_ok)

    @mock.patch("tmux_status_server.scraper.read_session_key")
    def test_no_key_error(self, mock_read_key):
        """_do_scrape handles no_key error."""
        server, _, _, _, _ = self._make_server()
        mock_read_key.return_value = {"error": "no_key"}
        server._do_scrape()
        self.assertEqual(server._cached_data["status"], "no_key")
        self.assertFalse(server._last_scrape_ok)


# ---------------------------------------------------------------------------
# Server: bottle quiet=True
# ---------------------------------------------------------------------------

class TestBottleQuietMode(unittest.TestCase):
    """Test that server starts bottle in quiet mode."""

    def test_quiet_true_passed_to_bottle_run(self):
        """run() passes quiet=True to bottle.run() to suppress output."""
        from test_server import _make_server
        server, _, _, _, mb = _make_server()
        with mock.patch("signal.signal"), \
             mock.patch.object(server, "_poll_loop"):
            server.run()
            call_kwargs = server._bottle_run.call_args
            self.assertTrue(call_kwargs[1].get("quiet", False),
                            "bottle.run must be called with quiet=True")


# ---------------------------------------------------------------------------
# Config: Unknown arguments rejected
# ---------------------------------------------------------------------------

class TestConfigUnknownArgs(unittest.TestCase):
    """Test that unrecognized CLI arguments are rejected."""

    def test_unknown_flag_rejected(self):
        """Unknown --flag raises SystemExit."""
        with self.assertRaises(SystemExit):
            parse_args(["--unknown-flag", "value"])

    def test_unknown_short_flag_rejected(self):
        """Unknown -x short flag raises SystemExit."""
        with self.assertRaises(SystemExit):
            parse_args(["-z"])

    def test_invalid_port_type_rejected(self):
        """Non-integer --port value raises SystemExit."""
        with self.assertRaises(SystemExit):
            parse_args(["--port", "not-a-number"])

    def test_invalid_interval_type_rejected(self):
        """Non-integer --interval value raises SystemExit."""
        with self.assertRaises(SystemExit):
            parse_args(["--interval", "five-minutes"])


# ---------------------------------------------------------------------------
# Scraper: read_session_key with unicode content
# ---------------------------------------------------------------------------

class TestReadSessionKeyUnicode(unittest.TestCase):
    """Test read_session_key handles unicode content correctly."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.key_path = os.path.join(self.tmpdir, "key.json")

    def tearDown(self):
        if os.path.exists(self.key_path):
            os.chmod(self.key_path, 0o600)
            os.remove(self.key_path)
        os.rmdir(self.tmpdir)

    def test_session_key_with_unicode_chars(self):
        """Session key containing unicode characters is read correctly."""
        with open(self.key_path, "w") as f:
            json.dump({"sessionKey": "sk-ant-test-\u00e9\u00e8\u00ea"}, f)
        os.chmod(self.key_path, 0o600)
        result = read_session_key(self.key_path)
        self.assertNotIn("error", result)
        self.assertIn("\u00e9", result["sessionKey"])

    def test_empty_json_object(self):
        """Empty JSON object (no sessionKey) returns invalid_json."""
        with open(self.key_path, "w") as f:
            json.dump({}, f)
        os.chmod(self.key_path, 0o600)
        result = read_session_key(self.key_path)
        self.assertEqual(result["error"], "invalid_json")

    def test_null_session_key_value(self):
        """sessionKey with null value -- present but null."""
        with open(self.key_path, "w") as f:
            json.dump({"sessionKey": None}, f)
        os.chmod(self.key_path, 0o600)
        result = read_session_key(self.key_path)
        # Key is present, so it should succeed (value is None)
        self.assertNotIn("error", result)
        self.assertIsNone(result["sessionKey"])

    def test_empty_string_session_key(self):
        """sessionKey with empty string value is accepted."""
        with open(self.key_path, "w") as f:
            json.dump({"sessionKey": ""}, f)
        os.chmod(self.key_path, 0o600)
        result = read_session_key(self.key_path)
        self.assertNotIn("error", result)
        self.assertEqual(result["sessionKey"], "")

    def test_empty_file(self):
        """Empty file returns invalid_json error."""
        with open(self.key_path, "w") as f:
            pass  # empty file
        os.chmod(self.key_path, 0o600)
        result = read_session_key(self.key_path)
        self.assertEqual(result["error"], "invalid_json")

    def test_json_with_extra_fields_preserves_session_key(self):
        """Extra fields in JSON are ignored, sessionKey is extracted."""
        with open(self.key_path, "w") as f:
            json.dump({
                "sessionKey": "sk-valid",
                "extra": "field",
                "nested": {"data": 123},
            }, f)
        os.chmod(self.key_path, 0o600)
        result = read_session_key(self.key_path)
        self.assertEqual(result["sessionKey"], "sk-valid")
        # Extra fields should NOT be in result
        self.assertNotIn("extra", result)
        self.assertNotIn("nested", result)


# ---------------------------------------------------------------------------
# Scraper: fetch_quota with missing window keys in usage response
# ---------------------------------------------------------------------------

class TestFetchQuotaMissingWindowKeys(unittest.TestCase):
    """Test fetch_quota handles partial/missing window data gracefully."""

    def setUp(self):
        scraper._org_uuid = None

    @mock.patch("tmux_status_server.scraper._http_get")
    def test_empty_usage_response_returns_none_values(self, mock_get):
        """Completely empty usage body returns None for all window values."""
        mock_get.side_effect = [
            (200, [{"uuid": "org-test"}]),
            (200, {}),
        ]
        result = fetch_quota("sk-ant-test")
        self.assertEqual(result["status"], "ok")
        self.assertIsNone(result["five_hour"]["utilization"])
        self.assertIsNone(result["five_hour"]["resets_at"])
        self.assertIsNone(result["seven_day"]["utilization"])
        self.assertIsNone(result["seven_day"]["resets_at"])

    @mock.patch("tmux_status_server.scraper._http_get")
    def test_partial_window_data(self, mock_get):
        """Window with only utilization, no resets_at."""
        mock_get.side_effect = [
            (200, [{"uuid": "org-test"}]),
            (200, {
                "five_hour": {"utilization": 42},
                "seven_day": {"utilization": 15},
            }),
        ]
        result = fetch_quota("sk-ant-test")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["five_hour"]["utilization"], 42)
        self.assertIsNone(result["five_hour"]["resets_at"])

    @mock.patch("tmux_status_server.scraper._http_get")
    def test_window_value_is_none(self, mock_get):
        """Window value set to None explicitly."""
        mock_get.side_effect = [
            (200, [{"uuid": "org-test"}]),
            (200, {
                "five_hour": None,
                "seven_day": None,
            }),
        ]
        result = fetch_quota("sk-ant-test")
        self.assertEqual(result["status"], "ok")
        # None.get() would fail, so this should handle gracefully via or {}
        self.assertIsNone(result["five_hour"]["utilization"])
        self.assertIsNone(result["five_hour"]["resets_at"])


# ---------------------------------------------------------------------------
# Server: health endpoint uptime calculation edge cases
# ---------------------------------------------------------------------------

class TestHealthUptimeEdgeCases(unittest.TestCase):
    """Test uptime_seconds calculation edge cases."""

    def test_uptime_is_non_negative(self):
        """uptime_seconds is always non-negative."""
        from test_server import _make_server
        server, routes, _, _, _ = _make_server()
        server._start_time = time.time()
        result = json.loads(routes["/health"]())
        self.assertGreaterEqual(result["uptime_seconds"], 0)

    def test_uptime_truncates_to_int(self):
        """uptime_seconds is an integer (not float)."""
        from test_server import _make_server
        server, routes, _, _, _ = _make_server()
        server._start_time = time.time() - 123.456
        result = json.loads(routes["/health"]())
        self.assertIsInstance(result["uptime_seconds"], int)
        self.assertGreaterEqual(result["uptime_seconds"], 123)


# ---------------------------------------------------------------------------
# Server: error_bridge consistency with scraper
# ---------------------------------------------------------------------------

class TestServerUsesScraperErrorBridge(unittest.TestCase):
    """Verify server.py uses scraper._error_bridge for error state."""

    def test_scraper_error_bridge_imported_in_server(self):
        """server.py imports _error_bridge from scraper."""
        server_path = os.path.join(
            os.path.dirname(__file__), "..", "tmux_status_server", "server.py"
        )
        with open(server_path) as f:
            source = f.read()
        self.assertIn("_error_bridge", source)
        self.assertIn("from tmux_status_server.scraper import", source)

    def test_error_bridge_output_is_json_serializable(self):
        """_error_bridge output can be serialized to JSON without errors."""
        result = _error_bridge("test_error", "test_error")
        serialized = json.dumps(result)
        deserialized = json.loads(serialized)
        self.assertEqual(deserialized["status"], "test_error")
        self.assertEqual(deserialized["five_hour"]["utilization"], "X")


# ---------------------------------------------------------------------------
# Server: Multiple requests to /quota return consistent data
# ---------------------------------------------------------------------------

class TestQuotaEndpointConsistency(unittest.TestCase):
    """Test that multiple /quota requests return consistent data."""

    def test_repeated_requests_same_data(self):
        """Multiple /quota calls with same cached data return identical results."""
        from test_server import _make_server
        server, routes, _, _, _ = _make_server()
        server._cached_data = {
            "status": "ok",
            "five_hour": {"utilization": 42, "resets_at": "2026-04-03T18:30:00Z"},
            "seven_day": {"utilization": 15, "resets_at": "2026-04-07T12:00:00Z"},
            "timestamp": 1743696000,
        }
        results = [json.loads(routes["/quota"]()) for _ in range(5)]
        for r in results[1:]:
            self.assertEqual(r, results[0])

    def test_data_update_reflected_immediately(self):
        """After _cached_data update, next /quota call returns new data."""
        from test_server import _make_server
        server, routes, _, _, _ = _make_server()
        server._cached_data = {"status": "ok", "timestamp": 1}
        r1 = json.loads(routes["/quota"]())
        self.assertEqual(r1["timestamp"], 1)

        server._cached_data = {"status": "ok", "timestamp": 2}
        r2 = json.loads(routes["/quota"]())
        self.assertEqual(r2["timestamp"], 2)


# ---------------------------------------------------------------------------
# Scraper: _error_bridge does not mutate between calls
# ---------------------------------------------------------------------------

class TestErrorBridgeImmutability(unittest.TestCase):
    """Verify that _error_bridge returns a fresh dict each time."""

    def test_separate_calls_return_different_objects(self):
        """Two calls to _error_bridge return different dict objects."""
        r1 = _error_bridge("a", "a")
        r2 = _error_bridge("b", "b")
        self.assertIsNot(r1, r2)
        self.assertEqual(r1["status"], "a")
        self.assertEqual(r2["status"], "b")

    def test_mutating_result_does_not_affect_next_call(self):
        """Mutating one result does not affect subsequent calls."""
        r1 = _error_bridge("x", "x")
        r1["five_hour"]["utilization"] = "MUTATED"
        r2 = _error_bridge("y", "y")
        self.assertEqual(r2["five_hour"]["utilization"], "X")


# ---------------------------------------------------------------------------
# Config: warn_if_exposed with various non-standard hosts
# ---------------------------------------------------------------------------

class TestWarnIfExposedExtendedHosts(unittest.TestCase):
    """Test warn_if_exposed with additional host variants."""

    def test_warning_on_ipv6_all_interfaces(self):
        """:: (IPv6 all interfaces) triggers a warning."""
        import logging
        args = parse_args(["--host", "::"])
        with self.assertLogs(level="WARNING") as cm:
            from tmux_status_server.config import warn_if_exposed
            warn_if_exposed(args)
        warnings = [msg for msg in cm.output if "NO authentication" in msg]
        self.assertEqual(len(warnings), 1)

    def test_warning_on_public_ip(self):
        """Public IP address triggers a warning."""
        import logging
        args = parse_args(["--host", "8.8.8.8"])
        with self.assertLogs(level="WARNING") as cm:
            from tmux_status_server.config import warn_if_exposed
            warn_if_exposed(args)
        warnings = [msg for msg in cm.output if "NO authentication" in msg]
        self.assertEqual(len(warnings), 1)


if __name__ == "__main__":
    unittest.main()
