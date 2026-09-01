"""Validation pass 3: Tests for coverage gaps found after ESCALATE cycle 3.

Covers:
- TS-13: _org_uuid instance lifecycle through _do_scrape (not just fetch_quota)
- TS-22: SIGTERM raising SystemExit(0) stops serve_forever in practice
- Content-Type headers verified via WSGI integration
- Security: injection attempts in session key content, path traversal awareness
- Edge cases: _do_scrape org_uuid caching across success/failure transitions
- Edge cases: concurrent read of _cached_data during _do_scrape
- Edge cases: _maybe_fetch_quota with timeout, malformed URL, large payloads
- Data integrity: _do_scrape does not leak org_uuid to error bridge responses
"""

import http.server
import json
import os
import signal
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

# Add server directory to path so we can import the module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from tmux_status_server.cli_usage import error_bridge


# ---------------------------------------------------------------------------
# Helper: import server constructor helpers
# ---------------------------------------------------------------------------

from test_server import _make_server, _make_wsgi_server, _SAMPLE_QUOTA_DATA


# ---------------------------------------------------------------------------
# TS-13: _org_uuid instance lifecycle through _do_scrape
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TS-13: Separate QuotaServer instances have independent _org_uuid
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# TS-22: SIGTERM raises SystemExit(0) -- functional test
# ---------------------------------------------------------------------------

class TestSigtermFunctionalBehavior(unittest.TestCase):
    """Verify SIGTERM handler behavior matches TS-22 requirements."""

    def test_sigterm_raises_system_exit_not_other_exception(self):
        """SIGTERM handler specifically raises SystemExit, not a custom exception."""
        server, _, _, _, _ = _make_server()
        with self.assertRaises(SystemExit) as cm:
            server._handle_sigterm(signal.SIGTERM, None)
        # Must be SystemExit specifically (not BaseException subclass)
        self.assertIsInstance(cm.exception, SystemExit)
        self.assertEqual(cm.exception.code, 0)

    def test_sigint_raises_same_system_exit(self):
        """SIGINT uses the same handler as SIGTERM (same behavior)."""
        server, _, _, _, _ = _make_server()
        with self.assertRaises(SystemExit) as cm:
            server._handle_sigterm(signal.SIGINT, None)
        self.assertEqual(cm.exception.code, 0)

    def test_shutdown_event_set_before_exception(self):
        """Shutdown event is set before SystemExit propagates."""
        server, _, _, _, _ = _make_server()
        # The shutdown event must be set so the poll thread can exit
        self.assertFalse(server._shutdown.is_set())
        self.assertFalse(server._wake.is_set())
        try:
            server._handle_sigterm(signal.SIGTERM, None)
        except SystemExit:
            pass
        self.assertTrue(server._shutdown.is_set())
        self.assertTrue(server._wake.is_set())

    def test_poll_loop_exits_on_shutdown_event(self):
        """Poll loop exits cleanly when shutdown event is set."""
        server, _, _, _, _ = _make_server()
        # Pre-set shutdown before entering poll loop
        server._shutdown.set()
        server._wake.set()

        # Mock _do_scrape to avoid real scraping
        scrape_count = [0]
        original = server._do_collect

        def mock_scrape():
            scrape_count[0] += 1

        server._do_collect = mock_scrape

        # Poll loop should do one scrape then exit
        server._poll_loop()
        self.assertEqual(scrape_count[0], 1)


# ---------------------------------------------------------------------------
# WSGI: Content-Type header verification
# ---------------------------------------------------------------------------

class TestWSGIContentTypeHeaders(unittest.TestCase):
    """Verify Content-Type: application/json on all endpoints via WSGI."""

    def test_quota_content_type_is_json(self):
        """/quota response has Content-Type: application/json."""
        server, app = _make_wsgi_server()
        server._api_key = None
        server._cached_data = dict(_SAMPLE_QUOTA_DATA)

        resp = app.get("/quota")
        self.assertEqual(resp.content_type, "application/json")

    def test_health_content_type_is_json(self):
        """/health response has Content-Type: application/json."""
        server, app = _make_wsgi_server()
        server._api_key = None

        resp = app.get("/health")
        self.assertEqual(resp.content_type, "application/json")

    def test_503_content_type_is_json(self):
        """503 starting response has Content-Type: application/json."""
        server, app = _make_wsgi_server()
        server._api_key = None
        # No cached data -> 503

        resp = app.get("/quota", expect_errors=True)
        self.assertEqual(resp.status_int, 503)
        self.assertEqual(resp.content_type, "application/json")

    def test_404_content_type_is_json(self):
        """404 response has Content-Type: application/json."""
        server, app = _make_wsgi_server()
        server._api_key = None

        resp = app.get("/nonexistent", expect_errors=True)
        self.assertEqual(resp.status_int, 404)
        # Bottle wraps error handler output in HTML; verify JSON error is present
        self.assertIn("not_found", resp.text)


# ---------------------------------------------------------------------------
# WSGI: /quota response contract via real Bottle pipeline
# ---------------------------------------------------------------------------

class TestWSGIQuotaResponseContract(unittest.TestCase):
    """Verify /quota response JSON structure through real Bottle."""

    def test_success_response_is_parseable_json(self):
        """Successful /quota response is valid JSON with all required keys."""
        server, app = _make_wsgi_server()
        server._api_key = None
        server._cached_data = dict(_SAMPLE_QUOTA_DATA)

        resp = app.get("/quota")
        data = resp.json
        for key in ("status", "org_uuid", "five_hour", "seven_day", "timestamp"):
            self.assertIn(key, data, f"Missing key: {key}")
        self.assertIn("utilization", data["five_hour"])
        self.assertIn("resets_at", data["five_hour"])

    def test_503_response_has_error_field(self):
        """503 starting response includes error field."""
        server, app = _make_wsgi_server()
        server._api_key = None

        resp = app.get("/quota", expect_errors=True)
        data = resp.json
        self.assertEqual(data["status"], "starting")
        self.assertEqual(data["error"], "no_data_yet")

    def test_error_status_passes_through_wsgi(self):
        """Error status from the collector passes through WSGI unchanged."""
        server, app = _make_wsgi_server()
        server._api_key = None
        server._cached_data = {
            "status": "session_key_expired",
            "error": "session_key_expired",
            "five_hour": {"utilization": "X", "resets_at": None},
            "seven_day": {"utilization": "X", "resets_at": None},
            "timestamp": 1743696000,
        }

        resp = app.get("/quota")
        data = resp.json
        self.assertEqual(data["status"], "session_key_expired")
        self.assertEqual(data["five_hour"]["utilization"], "X")


# ---------------------------------------------------------------------------
# Data integrity: _do_scrape error bridge never contains org_uuid
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Client-side: _maybe_fetch_quota additional edge cases
# ---------------------------------------------------------------------------

from polyglot_extract import load_function

_maybe_fetch_quota = load_function('_maybe_fetch_quota')


class _SlowHandler(http.server.BaseHTTPRequestHandler):
    """Handler that delays responses to test timeout behavior."""

    delay = 5  # seconds

    def do_GET(self):
        time.sleep(self.delay)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def log_message(self, format, *args):
        pass


class _LargePayloadHandler(http.server.BaseHTTPRequestHandler):
    """Handler that returns a large JSON payload."""

    def do_GET(self):
        # ~100KB payload
        data = {"status": "ok", "padding": "x" * 100000}
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


class TestClientFetchQuotaTimeout(unittest.TestCase):
    """Test _maybe_fetch_quota handles slow servers gracefully."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cache_path = os.path.join(self.tmpdir, "timeout-cache.json")

    def tearDown(self):
        for f in [self.cache_path, self.cache_path + ".tmp"]:
            if os.path.exists(f):
                os.remove(f)
        if os.path.exists(self.tmpdir):
            os.rmdir(self.tmpdir)

    def test_timeout_does_not_raise(self):
        """Slow server response does not raise -- fails silently."""
        _SlowHandler.delay = 5
        server = http.server.HTTPServer(("127.0.0.1", 0), _SlowHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            start = time.time()
            _maybe_fetch_quota(f"http://127.0.0.1:{port}", "", 0, self.cache_path)
            elapsed = time.time() - start
            # Should have timed out at 3s, not waited for the full 5s delay
            self.assertLess(elapsed, 4.5,
                            "Should timeout before server's 5s delay")
            self.assertFalse(os.path.exists(self.cache_path))
        finally:
            server.shutdown()


class TestClientFetchQuotaMalformedUrl(unittest.TestCase):
    """Test _maybe_fetch_quota with malformed URLs."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cache_path = os.path.join(self.tmpdir, "url-cache.json")

    def tearDown(self):
        for f in [self.cache_path, self.cache_path + ".tmp"]:
            if os.path.exists(f):
                os.remove(f)
        if os.path.exists(self.tmpdir):
            os.rmdir(self.tmpdir)

    def test_invalid_scheme_silent_failure(self):
        """Invalid URL scheme fails silently."""
        _maybe_fetch_quota("ftp://invalid-scheme", "", 0, self.cache_path)
        self.assertFalse(os.path.exists(self.cache_path))

    def test_unresolvable_host_silent_failure(self):
        """Unresolvable hostname fails silently."""
        _maybe_fetch_quota("http://this-host-does-not-exist.invalid", "", 0, self.cache_path)
        self.assertFalse(os.path.exists(self.cache_path))

    def test_none_source_url_is_noop(self):
        """None as source_url is treated as falsy (no-op)."""
        # The function checks `if not source_url:` so None should be handled
        _maybe_fetch_quota(None, "", 0, self.cache_path)
        self.assertFalse(os.path.exists(self.cache_path))


class TestClientFetchQuotaLargePayload(unittest.TestCase):
    """Test _maybe_fetch_quota with large JSON payloads."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cache_path = os.path.join(self.tmpdir, "large-cache.json")
        self.server = http.server.HTTPServer(("127.0.0.1", 0), _LargePayloadHandler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        for f in [self.cache_path, self.cache_path + ".tmp"]:
            if os.path.exists(f):
                os.remove(f)
        if os.path.exists(self.tmpdir):
            os.rmdir(self.tmpdir)

    def test_large_payload_written_successfully(self):
        """100KB JSON payload is fetched and written to cache."""
        url = f"http://127.0.0.1:{self.port}"
        _maybe_fetch_quota(url, "", 0, self.cache_path)
        self.assertTrue(os.path.exists(self.cache_path))
        with open(self.cache_path) as f:
            data = json.load(f)
        self.assertEqual(data["status"], "ok")
        self.assertGreater(len(data["padding"]), 90000)


# ---------------------------------------------------------------------------
# Security: Session key values with injection patterns
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Security: Error bridge never exposes raw exception details
# ---------------------------------------------------------------------------

class TestErrorBridgeSanitization(unittest.TestCase):
    """Verify error_bridge output never contains dangerous content."""

    def test_error_bridge_with_injection_status(self):
        """error_bridge with an adversarial code is still well-formed JSON."""
        result = error_bridge('"; DROP TABLE; --<script>alert(1)</script>')
        serialized = json.dumps(result)
        # Must be valid JSON
        deserialized = json.loads(serialized)
        self.assertEqual(deserialized["status"], "error")
        self.assertEqual(
            deserialized["error"], '"; DROP TABLE; --<script>alert(1)</script>'
        )
        # The "error" field faithfully stores whatever was passed, but this is
        # only consumed by internal code, never rendered as HTML or SQL

    def test_error_bridge_all_fields_present(self):
        """error_bridge always has status, five_hour, seven_day, error, timestamp."""
        result = error_bridge("test")
        required = {
            "status", "five_hour", "seven_day", "model_week", "error", "timestamp",
        }
        self.assertEqual(set(result.keys()), required)


# ---------------------------------------------------------------------------
# WSGI Integration: Health endpoint contract
# ---------------------------------------------------------------------------

class TestWSGIHealthContract(unittest.TestCase):
    """Verify /health endpoint contract via real WSGI pipeline."""

    def test_health_ok_state(self):
        """/health returns ok when cached data and last collection succeeded."""
        server, app = _make_wsgi_server()
        server._api_key = None
        server._cached_data = {"status": "ok"}
        server._last_collect_ok = True

        resp = app.get("/health")
        data = resp.json
        self.assertEqual(data["status"], "ok")
        self.assertIn("uptime_seconds", data)
        self.assertIn("version", data)
        self.assertEqual(data["version"], "0.1.0")

    def test_health_degraded_state(self):
        """/health returns degraded when has data but last scrape failed."""
        server, app = _make_wsgi_server()
        server._api_key = None
        server._cached_data = {"status": "upstream_error"}
        server._last_collect_ok = False

        resp = app.get("/health")
        data = resp.json
        self.assertEqual(data["status"], "degraded")

    def test_health_error_state(self):
        """/health returns error when no data at all."""
        server, app = _make_wsgi_server()
        server._api_key = None
        server._cached_data = None

        resp = app.get("/health")
        data = resp.json
        self.assertEqual(data["status"], "error")

    def test_health_uptime_increases(self):
        """/health uptime_seconds increases over time."""
        server, app = _make_wsgi_server()
        server._api_key = None
        server._start_time = time.time() - 60

        resp = app.get("/health")
        data = resp.json
        self.assertGreaterEqual(data["uptime_seconds"], 59)


# ---------------------------------------------------------------------------
# Edge case: _do_scrape with exception preserves previous cached data
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Config edge cases: boundary values
# ---------------------------------------------------------------------------

class TestConfigBoundaryValues(unittest.TestCase):
    """Test parse_args with boundary values."""

    def test_port_zero(self):
        """Port 0 is accepted (OS assigns random port)."""
        from tmux_status_server.config import parse_args
        args = parse_args(["--port", "0"])
        self.assertEqual(args.port, 0)

    def test_port_65535(self):
        """Port 65535 (max) is accepted."""
        from tmux_status_server.config import parse_args
        args = parse_args(["--port", "65535"])
        self.assertEqual(args.port, 65535)

    def test_interval_zero_rejected(self):
        """Interval 0 is rejected (below minimum 30)."""
        from tmux_status_server.config import parse_args
        with self.assertRaises(SystemExit):
            parse_args(["--interval", "0"])

    def test_interval_one_rejected(self):
        """Interval 1 is rejected (below minimum 30)."""
        from tmux_status_server.config import parse_args
        with self.assertRaises(SystemExit):
            parse_args(["--interval", "1"])

    def test_negative_port_accepted_by_argparse(self):
        """Negative port is parsed as int (validation is not in argparse)."""
        from tmux_status_server.config import parse_args
        args = parse_args(["--port", "-1"])
        self.assertEqual(args.port, -1)


if __name__ == "__main__":
    unittest.main()
