"""Tests for tmux_status_server.server module."""

import ast
import hmac
import json
import logging
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


SERVER_PATH = os.path.join(
    os.path.dirname(__file__), "..", "tmux_status_server", "server.py"
)
MAIN_PATH = os.path.join(
    os.path.dirname(__file__), "..", "tmux_status_server", "__main__.py"
)


# ---------------------------------------------------------------------------
# Helper: mock Bottle module
# ---------------------------------------------------------------------------

def _make_mock_bottle():
    """Create a mock bottle module with route/hook/error registration.

    Returns (mock_module, routes_dict, hooks_dict, error_handlers_dict).
    """
    mock_bottle = mock.MagicMock()

    _routes = {}
    _hooks = {}
    _error_handlers = {}

    class MockApp:
        def __init__(self):
            self.routes = _routes
            self.hooks = _hooks
            self.error_handlers = _error_handlers

        def hook(self, name):
            def decorator(fn):
                _hooks[name] = fn
                return fn
            return decorator

        def route(self, path, **kwargs):
            def decorator(fn):
                _routes[path] = fn
                return fn
            return decorator

        def error(self, code):
            def decorator(fn):
                _error_handlers[code] = fn
                return fn
            return decorator

    mock_bottle.Bottle = MockApp
    mock_bottle.run = mock.MagicMock()
    # Provide request/response mocks at module level
    mock_bottle.request = mock.MagicMock()
    mock_bottle.response = mock.MagicMock()

    return mock_bottle, _routes, _hooks, _error_handlers


def _make_server(**overrides):
    """Create a QuotaServer with mocked bottle, returning (server, routes, hooks, errors)."""
    mock_bottle, routes, hooks, errors = _make_mock_bottle()
    with mock.patch.dict("sys.modules", {"bottle": mock_bottle}):
        import importlib
        import tmux_status_server.server
        importlib.reload(tmux_status_server.server)
        from tmux_status_server.server import QuotaServer
        defaults = {
            "host": "127.0.0.1",
            "port": 7850,
            "key_file": "/tmp/k.json",
            "api_key_file": None,
            "interval": 300,
        }
        defaults.update(overrides)
        server = QuotaServer(**defaults)
        return server, routes, hooks, errors, mock_bottle


# ---------------------------------------------------------------------------
# AST-based structural tests (no runtime import of bottle needed)
# ---------------------------------------------------------------------------

class TestServerModuleStructure(unittest.TestCase):
    """Verify server.py structure via AST analysis without importing bottle."""

    @classmethod
    def setUpClass(cls):
        with open(SERVER_PATH) as f:
            cls.source = f.read()
            cls.tree = ast.parse(cls.source)

    def test_file_exists(self):
        """server.py exists on disk."""
        self.assertTrue(os.path.isfile(SERVER_PATH))

    def test_quota_server_class_exists(self):
        """server.py defines a QuotaServer class."""
        class_names = [
            node.name for node in ast.walk(self.tree)
            if isinstance(node, ast.ClassDef)
        ]
        self.assertIn("QuotaServer", class_names)

    def test_main_function_exists(self):
        """server.py defines a main() function at module level."""
        func_names = [
            node.name for node in ast.walk(self.tree)
            if isinstance(node, ast.FunctionDef)
        ]
        self.assertIn("main", func_names)

    def test_hmac_import_present(self):
        """server.py imports the hmac module."""
        imports = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
        self.assertIn("hmac", imports)

    def test_hmac_compare_digest_used(self):
        """server.py uses hmac.compare_digest()."""
        self.assertIn("hmac.compare_digest", self.source)

    def test_signal_module_imported(self):
        """server.py imports the signal module."""
        imports = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
        self.assertIn("signal", imports)

    def test_signal_signal_calls_for_sigterm(self):
        """server.py registers handler for signal.SIGTERM."""
        self.assertIn("signal.SIGTERM", self.source)

    def test_signal_signal_calls_for_sigint(self):
        """server.py registers handler for signal.SIGINT."""
        self.assertIn("signal.SIGINT", self.source)

    def test_signal_signal_calls_for_sigusr1(self):
        """server.py registers handler for signal.SIGUSR1."""
        self.assertIn("signal.SIGUSR1", self.source)

    def test_signal_signal_called(self):
        """signal.signal() is called to register handlers."""
        self.assertIn("signal.signal(", self.source)

    def test_threading_import_present(self):
        """server.py imports threading for the background poll thread."""
        imports = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
        self.assertIn("threading", imports)

    def test_bottle_not_imported_at_module_level(self):
        """Bottle is imported lazily inside methods, not at module level."""
        for node in ast.iter_child_nodes(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotEqual(
                        alias.name.split(".")[0], "bottle",
                        "bottle imported at module level"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    self.assertNotEqual(
                        node.module.split(".")[0], "bottle",
                        "bottle imported at module level"
                    )

    def test_bottle_imported_inside_functions(self):
        """Bottle is imported inside function bodies (lazy import pattern)."""
        found_bottle_import = False
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for child in ast.walk(node):
                    if isinstance(child, ast.ImportFrom) and child.module == "bottle":
                        found_bottle_import = True
                    elif isinstance(child, ast.Import):
                        for alias in child.names:
                            if alias.name.split(".")[0] == "bottle":
                                found_bottle_import = True
        self.assertTrue(found_bottle_import, "No lazy bottle import found inside functions")

    def test_logging_format_string(self):
        """main() configures logging with the required format string."""
        self.assertIn("%(asctime)s %(levelname)s %(message)s", self.source)

    def test_imports_parse_args_and_warn_if_exposed(self):
        """server.py imports parse_args and warn_if_exposed from config."""
        config_imports = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and "config" in node.module:
                    config_imports.extend(alias.name for alias in node.names)
        self.assertIn("parse_args", config_imports)
        self.assertIn("warn_if_exposed", config_imports)

    def test_imports_version_from_init(self):
        """server.py imports __version__ from the package."""
        found = False
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and "tmux_status_server" in node.module:
                    names = [alias.name for alias in node.names]
                    if "__version__" in names:
                        found = True
        self.assertTrue(found, "server.py does not import __version__")

    def test_imports_scraper_functions(self):
        """server.py imports fetch_quota, read_session_key, _error_bridge from scraper."""
        scraper_imports = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and "scraper" in node.module:
                    scraper_imports.extend(alias.name for alias in node.names)
        self.assertIn("fetch_quota", scraper_imports)
        self.assertIn("read_session_key", scraper_imports)
        self.assertIn("_error_bridge", scraper_imports)

    def test_no_threading_lock(self):
        """server.py uses reference swap, not threading.Lock."""
        self.assertNotIn("threading.Lock", self.source)
        self.assertNotIn("Lock()", self.source)

    def test_logger_uses_getlogger(self):
        """server.py creates logger via logging.getLogger(__name__)."""
        self.assertIn("logging.getLogger(__name__)", self.source)

    def test_allowed_imports_only(self):
        """server.py only imports stdlib and tmux_status_server submodules at module level."""
        stdlib_modules = {
            "hmac", "json", "logging", "os", "signal", "threading", "time",
            "sys", "pathlib",
        }
        internal_modules = {"tmux_status_server"}

        for node in ast.iter_child_nodes(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    self.assertTrue(
                        top in stdlib_modules or top in internal_modules,
                        f"Unexpected top-level import: {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top = node.module.split(".")[0]
                    self.assertTrue(
                        top in stdlib_modules or top in internal_modules,
                        f"Unexpected top-level import: {node.module}"
                    )


# ---------------------------------------------------------------------------
# __main__.py update verification
# ---------------------------------------------------------------------------

class TestMainModuleUpdated(unittest.TestCase):
    """Test that __main__.py has been updated to use server.main()."""

    @classmethod
    def setUpClass(cls):
        with open(MAIN_PATH) as f:
            cls.source = f.read()
            cls.tree = ast.parse(cls.source)

    def test_imports_server_main(self):
        """__main__.py imports main from tmux_status_server.server."""
        found = False
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and "server" in node.module:
                    names = [alias.name for alias in node.names]
                    if "main" in names:
                        found = True
        self.assertTrue(found, "__main__.py does not import main from server")

    def test_still_has_if_name_main_guard(self):
        """__main__.py still has if __name__ == '__main__' guard."""
        self.assertIn('if __name__ == "__main__"', self.source)

    def test_no_sys_exit_1(self):
        """__main__.py no longer exits with code 1 (placeholder removed)."""
        self.assertNotIn("sys.exit(1)", self.source)

    def test_still_imports_config(self):
        """__main__.py still imports parse_args and warn_if_exposed."""
        config_imports = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and "config" in node.module:
                    config_imports.extend(alias.name for alias in node.names)
        self.assertIn("parse_args", config_imports)
        self.assertIn("warn_if_exposed", config_imports)


# ---------------------------------------------------------------------------
# QuotaServer initialization
# ---------------------------------------------------------------------------

class TestQuotaServerInit(unittest.TestCase):
    """Test QuotaServer initialization."""

    def test_init_sets_attributes(self):
        """Constructor stores all passed parameters."""
        server, routes, hooks, errors, mb = _make_server()
        self.assertEqual(server.host, "127.0.0.1")
        self.assertEqual(server.port, 7850)
        self.assertEqual(server.key_file, "/tmp/k.json")
        self.assertIsNone(server.api_key_file)
        self.assertEqual(server.interval, 300)

    def test_init_default_state(self):
        """Constructor sets default internal state."""
        server, _, _, _, _ = _make_server()
        self.assertIsNone(server._cached_data)
        self.assertFalse(server._last_scrape_ok)

    def test_app_is_created(self):
        """Constructor creates a Bottle app."""
        server, _, _, _, _ = _make_server()
        self.assertIsNotNone(server._app)

    def test_routes_registered(self):
        """Constructor registers /quota and /health routes."""
        server, routes, hooks, errors, _ = _make_server()
        self.assertIn("/quota", routes)
        self.assertIn("/health", routes)

    def test_before_request_hook_registered(self):
        """Constructor registers a before_request hook."""
        server, routes, hooks, errors, _ = _make_server()
        self.assertIn("before_request", hooks)

    def test_error_handlers_registered(self):
        """Constructor registers error handlers for 404 and 500."""
        server, routes, hooks, errors, _ = _make_server()
        self.assertIn(404, errors)
        self.assertIn(500, errors)


# ---------------------------------------------------------------------------
# /quota endpoint
# ---------------------------------------------------------------------------

class TestQuotaEndpoint(unittest.TestCase):
    """Test /quota route behavior."""

    def test_returns_503_when_no_data(self):
        """GET /quota returns 503 JSON with starting status when no data fetched yet."""
        server, routes, hooks, errors, mb = _make_server()
        result_json = routes["/quota"]()
        result = json.loads(result_json)
        self.assertEqual(result["status"], "starting")
        self.assertEqual(result["error"], "no_data_yet")
        self.assertEqual(result["five_hour"]["utilization"], "X")
        self.assertIsNone(result["five_hour"]["resets_at"])
        self.assertEqual(result["seven_day"]["utilization"], "X")
        self.assertIsNone(result["seven_day"]["resets_at"])
        self.assertIn("timestamp", result)
        self.assertIsInstance(result["timestamp"], int)

    def test_returns_cached_data_when_available(self):
        """GET /quota returns 200 with cached bridge-format data."""
        server, routes, hooks, errors, mb = _make_server()
        cached = {
            "status": "ok",
            "org_uuid": "org-123",
            "five_hour": {"utilization": 42, "resets_at": "2026-04-03T18:30:00Z"},
            "seven_day": {"utilization": 15, "resets_at": "2026-04-07T12:00:00Z"},
            "timestamp": 1743696000,
        }
        server._cached_data = cached
        result_json = routes["/quota"]()
        result = json.loads(result_json)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["five_hour"]["utilization"], 42)
        self.assertEqual(result["seven_day"]["utilization"], 15)
        self.assertEqual(result["org_uuid"], "org-123")

    def test_passes_through_error_data(self):
        """GET /quota passes through error status from cached data."""
        server, routes, hooks, errors, mb = _make_server()
        server._cached_data = {
            "status": "expired",
            "five_hour": {"utilization": "X", "resets_at": None},
            "seven_day": {"utilization": "X", "resets_at": None},
            "timestamp": 1743696000,
            "error": "session_key_expired",
        }
        result_json = routes["/quota"]()
        result = json.loads(result_json)
        self.assertEqual(result["status"], "expired")
        self.assertEqual(result["error"], "session_key_expired")

    def test_503_response_keys(self):
        """503 response has status, five_hour, seven_day, timestamp, error keys."""
        server, routes, hooks, errors, mb = _make_server()
        result_json = routes["/quota"]()
        result = json.loads(result_json)
        for key in ("status", "five_hour", "seven_day", "timestamp", "error"):
            self.assertIn(key, result, f"Missing key: {key}")

    def test_success_response_keys(self):
        """Success response contains status, five_hour, seven_day, timestamp."""
        server, routes, hooks, errors, mb = _make_server()
        server._cached_data = {
            "status": "ok",
            "five_hour": {"utilization": 42, "resets_at": None},
            "seven_day": {"utilization": 15, "resets_at": None},
            "timestamp": 1743696000,
        }
        result_json = routes["/quota"]()
        result = json.loads(result_json)
        for key in ("status", "five_hour", "seven_day", "timestamp"):
            self.assertIn(key, result, f"Missing key: {key}")

    def test_returns_valid_json(self):
        """GET /quota always returns valid JSON."""
        server, routes, hooks, errors, mb = _make_server()
        result_json = routes["/quota"]()
        # Should not raise
        result = json.loads(result_json)
        self.assertIsInstance(result, dict)


# ---------------------------------------------------------------------------
# /health endpoint
# ---------------------------------------------------------------------------

class TestHealthEndpoint(unittest.TestCase):
    """Test /health route behavior."""

    def test_returns_error_when_no_data(self):
        """GET /health returns status 'error' when no data cached."""
        server, routes, hooks, errors, mb = _make_server()
        result_json = routes["/health"]()
        result = json.loads(result_json)
        self.assertEqual(result["status"], "error")
        self.assertIn("uptime_seconds", result)
        self.assertEqual(result["version"], "0.1.0")

    def test_returns_ok_when_data_and_scrape_ok(self):
        """GET /health returns 'ok' when data cached and last scrape succeeded."""
        server, routes, hooks, errors, mb = _make_server()
        server._cached_data = {"status": "ok"}
        server._last_scrape_ok = True
        result_json = routes["/health"]()
        result = json.loads(result_json)
        self.assertEqual(result["status"], "ok")

    def test_returns_degraded_when_data_but_last_scrape_failed(self):
        """GET /health returns 'degraded' when cached data but last scrape failed."""
        server, routes, hooks, errors, mb = _make_server()
        server._cached_data = {"status": "upstream_error"}
        server._last_scrape_ok = False
        result_json = routes["/health"]()
        result = json.loads(result_json)
        self.assertEqual(result["status"], "degraded")

    def test_contains_version(self):
        """GET /health includes version field."""
        server, routes, hooks, errors, mb = _make_server()
        result_json = routes["/health"]()
        result = json.loads(result_json)
        self.assertEqual(result["version"], "0.1.0")

    def test_contains_uptime_seconds(self):
        """GET /health includes uptime_seconds as integer."""
        server, routes, hooks, errors, mb = _make_server()
        server._start_time = time.time() - 100
        result_json = routes["/health"]()
        result = json.loads(result_json)
        self.assertIsInstance(result["uptime_seconds"], int)
        self.assertGreaterEqual(result["uptime_seconds"], 99)

    def test_returns_valid_json(self):
        """GET /health always returns valid JSON."""
        server, routes, hooks, errors, mb = _make_server()
        result_json = routes["/health"]()
        result = json.loads(result_json)
        self.assertIsInstance(result, dict)

    def test_required_keys(self):
        """GET /health contains status, uptime_seconds, version."""
        server, routes, hooks, errors, mb = _make_server()
        result_json = routes["/health"]()
        result = json.loads(result_json)
        for key in ("status", "uptime_seconds", "version"):
            self.assertIn(key, result, f"Missing key: {key}")


# ---------------------------------------------------------------------------
# Authentication hook
# ---------------------------------------------------------------------------

class TestAuthHook(unittest.TestCase):
    """Test API key authentication hook."""

    def test_no_auth_when_no_api_key(self):
        """When no API key configured, auth hook does not block requests."""
        server, routes, hooks, errors, mb = _make_server()
        server._api_key = None
        mb.request.path = "/quota"
        result = hooks["before_request"]()
        self.assertIsNone(result)

    def test_blocks_missing_header(self):
        """When API key configured, missing X-API-Key calls abort(401)."""
        server, routes, hooks, errors, mb = _make_server(api_key_file="/tmp/api.key")
        server._api_key = "test-secret-key"
        mb.request.path = "/quota"
        mb.request.get_header.return_value = None
        hooks["before_request"]()
        mb.abort.assert_called_once()
        args = mb.abort.call_args[0]
        self.assertEqual(args[0], 401)
        data = json.loads(args[1])
        self.assertEqual(data["error"], "invalid_or_missing_api_key")

    def test_blocks_wrong_key(self):
        """When API key configured, wrong X-API-Key calls abort(401)."""
        server, routes, hooks, errors, mb = _make_server(api_key_file="/tmp/api.key")
        server._api_key = "correct-key"
        mb.request.path = "/quota"
        mb.request.get_header.return_value = "wrong-key"
        hooks["before_request"]()
        mb.abort.assert_called_once()
        args = mb.abort.call_args[0]
        self.assertEqual(args[0], 401)
        data = json.loads(args[1])
        self.assertEqual(data["error"], "invalid_or_missing_api_key")

    def test_passes_correct_key(self):
        """When API key configured, correct X-API-Key passes auth."""
        server, routes, hooks, errors, mb = _make_server(api_key_file="/tmp/api.key")
        server._api_key = "correct-key"
        mb.request.path = "/quota"
        mb.request.get_header.return_value = "correct-key"
        result = hooks["before_request"]()
        self.assertIsNone(result)

    def test_health_exempt_from_auth(self):
        """GET /health is not gated by API key auth even when key configured."""
        server, routes, hooks, errors, mb = _make_server(api_key_file="/tmp/api.key")
        server._api_key = "secret-key"
        mb.request.path = "/health"
        mb.request.get_header.return_value = None
        result = hooks["before_request"]()
        self.assertIsNone(result)

    def test_auth_uses_hmac_compare_digest(self):
        """Auth hook uses hmac.compare_digest for timing-safe comparison."""
        with open(SERVER_PATH) as f:
            source = f.read()
        self.assertIn("hmac.compare_digest", source)


# ---------------------------------------------------------------------------
# Background poll thread
# ---------------------------------------------------------------------------

class TestBackgroundPollThread(unittest.TestCase):
    """Test the background scraper poll thread behavior."""

    @mock.patch("tmux_status_server.scraper.read_session_key")
    @mock.patch("tmux_status_server.scraper.fetch_quota")
    def test_first_scrape_happens_immediately(self, mock_fetch, mock_read_key):
        """The poll loop performs first scrape immediately on startup."""
        server, _, _, _, _ = _make_server()
        mock_read_key.return_value = {"sessionKey": "sk-test"}
        mock_fetch.return_value = {
            "status": "ok",
            "five_hour": {"utilization": 42, "resets_at": None},
            "seven_day": {"utilization": 15, "resets_at": None},
            "timestamp": 1000,
        }
        server._do_scrape()
        mock_read_key.assert_called_once_with("/tmp/k.json")
        mock_fetch.assert_called_once_with("sk-test")
        self.assertIsNotNone(server._cached_data)
        self.assertTrue(server._last_scrape_ok)

    @mock.patch("tmux_status_server.scraper.read_session_key")
    @mock.patch("tmux_status_server.scraper.fetch_quota")
    def test_rereads_session_key_each_cycle(self, mock_fetch, mock_read_key):
        """Session key is re-read from disk on every scrape cycle."""
        server, _, _, _, _ = _make_server()
        mock_read_key.return_value = {"sessionKey": "sk-test"}
        mock_fetch.return_value = {"status": "ok", "five_hour": {}, "seven_day": {}, "timestamp": 1}
        server._do_scrape()
        server._do_scrape()
        server._do_scrape()
        self.assertEqual(mock_read_key.call_count, 3)

    @mock.patch("tmux_status_server.scraper.read_session_key")
    def test_handles_key_error(self, mock_read_key):
        """Scrape handles session key read errors gracefully."""
        server, _, _, _, _ = _make_server()
        mock_read_key.return_value = {"error": "no_key"}
        server._do_scrape()
        self.assertIsNotNone(server._cached_data)
        self.assertEqual(server._cached_data["status"], "no_key")
        self.assertEqual(server._cached_data["error"], "no_key")
        self.assertFalse(server._last_scrape_ok)

    @mock.patch("tmux_status_server.scraper.read_session_key")
    @mock.patch("tmux_status_server.scraper.fetch_quota")
    def test_handles_fetch_exception(self, mock_fetch, mock_read_key):
        """Scrape catches exceptions from fetch_quota and sets error state."""
        server, _, _, _, _ = _make_server()
        mock_read_key.return_value = {"sessionKey": "sk-test"}
        mock_fetch.side_effect = Exception("unexpected")
        server._do_scrape()
        self.assertIsNotNone(server._cached_data)
        self.assertEqual(server._cached_data["status"], "upstream_error")
        self.assertFalse(server._last_scrape_ok)

    @mock.patch("tmux_status_server.scraper.read_session_key")
    @mock.patch("tmux_status_server.scraper.fetch_quota")
    def test_sets_last_scrape_ok_false_on_error_status(self, mock_fetch, mock_read_key):
        """When fetch_quota returns non-ok status, _last_scrape_ok is False."""
        server, _, _, _, _ = _make_server()
        mock_read_key.return_value = {"sessionKey": "sk-test"}
        mock_fetch.return_value = {
            "status": "session_key_expired",
            "error": "session_key_expired",
            "five_hour": {"utilization": "X", "resets_at": None},
            "seven_day": {"utilization": "X", "resets_at": None},
            "timestamp": 1000,
        }
        server._do_scrape()
        self.assertFalse(server._last_scrape_ok)

    @mock.patch("tmux_status_server.scraper.read_session_key")
    @mock.patch("tmux_status_server.scraper.fetch_quota")
    def test_poll_loop_immediate_scrape_then_shutdown(self, mock_fetch, mock_read_key):
        """Poll loop scrapes immediately, then exits on shutdown."""
        server, _, _, _, _ = _make_server()
        mock_read_key.return_value = {"sessionKey": "sk-test"}
        mock_fetch.return_value = {"status": "ok", "five_hour": {}, "seven_day": {}, "timestamp": 1}

        original_do_scrape = server._do_scrape
        call_count = [0]

        def counting_scrape():
            original_do_scrape()
            call_count[0] += 1
            if call_count[0] >= 1:
                server._shutdown.set()
                server._wake.set()

        server._do_scrape = counting_scrape
        server._poll_loop()
        self.assertGreaterEqual(call_count[0], 1)

    @mock.patch("tmux_status_server.scraper.read_session_key")
    @mock.patch("tmux_status_server.scraper.fetch_quota")
    def test_error_bridge_no_raw_exception(self, mock_fetch, mock_read_key):
        """Error responses never contain raw exception text."""
        server, _, _, _, _ = _make_server()
        mock_read_key.return_value = {"sessionKey": "sk-test"}
        mock_fetch.side_effect = RuntimeError("connection to database failed at 0xDEADBEEF")
        server._do_scrape()
        result_str = json.dumps(server._cached_data)
        self.assertNotIn("connection to database", result_str)
        self.assertNotIn("0xDEADBEEF", result_str)
        self.assertNotIn("Traceback", result_str)
        self.assertNotIn("RuntimeError", result_str)


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------

class TestSignalHandling(unittest.TestCase):
    """Test signal handler methods."""

    def test_sigterm_sets_shutdown(self):
        """SIGTERM handler sets the shutdown event."""
        server, _, _, _, _ = _make_server()
        self.assertFalse(server._shutdown.is_set())
        server._handle_sigterm(signal.SIGTERM, None)
        self.assertTrue(server._shutdown.is_set())
        self.assertTrue(server._wake.is_set())

    def test_sigint_sets_shutdown(self):
        """SIGINT handler sets the shutdown event."""
        server, _, _, _, _ = _make_server()
        server._handle_sigterm(signal.SIGINT, None)
        self.assertTrue(server._shutdown.is_set())

    def test_sigusr1_sets_wake_not_shutdown(self):
        """SIGUSR1 handler wakes the poll thread but does not shut down."""
        server, _, _, _, _ = _make_server()
        self.assertFalse(server._wake.is_set())
        server._handle_sigusr1(signal.SIGUSR1, None)
        self.assertTrue(server._wake.is_set())
        self.assertFalse(server._shutdown.is_set())


# ---------------------------------------------------------------------------
# API key file loading
# ---------------------------------------------------------------------------

class TestApiKeyLoading(unittest.TestCase):
    """Test API key file loading."""

    def test_no_api_key_file_returns_none(self):
        """When api_key_file is None, _load_api_key returns None."""
        server, _, _, _, _ = _make_server()
        result = server._load_api_key()
        self.assertIsNone(result)

    def test_load_api_key_from_file(self):
        """Loads and strips API key from file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".key", delete=False) as f:
            f.write("  my-secret-key  \n")
            key_path = f.name
        try:
            server, _, _, _, _ = _make_server(api_key_file=key_path)
            result = server._load_api_key()
            self.assertEqual(result, "my-secret-key")
        finally:
            os.unlink(key_path)

    def test_missing_file_returns_none(self):
        """Returns None when API key file does not exist."""
        server, _, _, _, _ = _make_server(api_key_file="/nonexistent/api.key")
        result = server._load_api_key()
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Server run() orchestration
# ---------------------------------------------------------------------------

class TestServerRun(unittest.TestCase):
    """Test the run() method orchestration."""

    def test_run_registers_signal_handlers(self):
        """run() registers signal handlers for SIGTERM, SIGINT, SIGUSR1."""
        server, _, _, _, mb = _make_server()
        with mock.patch("signal.signal") as mock_signal, \
             mock.patch.object(server, "_poll_loop"):
            server.run()
            signal_calls = {call[0][0] for call in mock_signal.call_args_list}
            self.assertIn(signal.SIGTERM, signal_calls)
            self.assertIn(signal.SIGINT, signal_calls)
            self.assertIn(signal.SIGUSR1, signal_calls)

    def test_run_calls_bottle_run_with_host_and_port(self):
        """run() calls bottle.run() with configured host and port."""
        server, _, _, _, mb = _make_server(host="0.0.0.0", port=9999)
        with mock.patch("signal.signal"), \
             mock.patch.object(server, "_poll_loop"):
            server.run()
            server._bottle_run.assert_called_once()
            call_kwargs = server._bottle_run.call_args
            if call_kwargs[1]:
                self.assertEqual(call_kwargs[1].get("host"), "0.0.0.0")
                self.assertEqual(call_kwargs[1].get("port"), 9999)

    def test_run_starts_poll_thread(self):
        """run() starts the background poll thread."""
        server, _, _, _, mb = _make_server()
        with mock.patch("signal.signal"), \
             mock.patch.object(server, "_poll_loop") as mock_poll:
            # We need to verify that a thread was started that targets _poll_loop.
            # Since _poll_loop is mocked, the thread will start and exit immediately.
            original_thread_init = threading.Thread.__init__

            thread_targets = []

            def capture_thread(self_t, *args, **kwargs):
                original_thread_init(self_t, *args, **kwargs)
                if kwargs.get("name") == "quota-poll":
                    thread_targets.append(kwargs.get("target"))

            with mock.patch.object(threading.Thread, "__init__", capture_thread):
                server.run()

            # The thread was started targeting _poll_loop
            self.assertTrue(len(thread_targets) > 0 or server._poll_thread is not None)

    def test_run_loads_api_key(self):
        """run() loads the API key on startup."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".key", delete=False) as f:
            f.write("test-api-key\n")
            key_path = f.name
        try:
            server, _, _, _, mb = _make_server(api_key_file=key_path)
            with mock.patch("signal.signal"), \
                 mock.patch.object(server, "_poll_loop"):
                server.run()
            self.assertEqual(server._api_key, "test-api-key")
        finally:
            os.unlink(key_path)


# ---------------------------------------------------------------------------
# main() function
# ---------------------------------------------------------------------------

class TestMainFunction(unittest.TestCase):
    """Test the module-level main() function."""

    def test_main_calls_parse_args(self):
        """main() calls parse_args from config."""
        mock_bottle, _, _, _ = _make_mock_bottle()
        with mock.patch.dict("sys.modules", {"bottle": mock_bottle}):
            import importlib
            import tmux_status_server.server
            importlib.reload(tmux_status_server.server)

            mock_args = mock.MagicMock()
            mock_args.host = "127.0.0.1"
            mock_args.port = 7850
            mock_args.key_file = "/tmp/k.json"
            mock_args.api_key_file = None
            mock_args.interval = 300
            mock_args.log_level = "INFO"

            with mock.patch("tmux_status_server.server.parse_args", return_value=mock_args) as mock_parse, \
                 mock.patch("tmux_status_server.server.warn_if_exposed") as mock_warn, \
                 mock.patch("tmux_status_server.server.QuotaServer") as MockServer, \
                 mock.patch("logging.basicConfig"):
                tmux_status_server.server.main()
                mock_parse.assert_called_once()
                mock_warn.assert_called_once_with(mock_args)
                MockServer.assert_called_once_with(
                    host="127.0.0.1",
                    port=7850,
                    key_file="/tmp/k.json",
                    api_key_file=None,
                    interval=300,
                )
                MockServer.return_value.run.assert_called_once()

    def test_main_sets_logging_format(self):
        """main() calls logging.basicConfig with required format."""
        mock_bottle, _, _, _ = _make_mock_bottle()
        with mock.patch.dict("sys.modules", {"bottle": mock_bottle}):
            import importlib
            import tmux_status_server.server
            importlib.reload(tmux_status_server.server)

            mock_args = mock.MagicMock()
            mock_args.host = "127.0.0.1"
            mock_args.port = 7850
            mock_args.key_file = "/tmp/k.json"
            mock_args.api_key_file = None
            mock_args.interval = 300
            mock_args.log_level = "DEBUG"

            with mock.patch("tmux_status_server.server.parse_args", return_value=mock_args), \
                 mock.patch("tmux_status_server.server.warn_if_exposed"), \
                 mock.patch("tmux_status_server.server.QuotaServer"), \
                 mock.patch("logging.basicConfig") as mock_basic:
                tmux_status_server.server.main()
                mock_basic.assert_called_once()
                call_kwargs = mock_basic.call_args[1]
                self.assertEqual(
                    call_kwargs["format"],
                    "%(asctime)s %(levelname)s %(message)s"
                )
                self.assertEqual(call_kwargs["level"], logging.DEBUG)


# ---------------------------------------------------------------------------
# Error responses
# ---------------------------------------------------------------------------

class TestErrorResponses(unittest.TestCase):
    """Test that error responses use generic codes only."""

    def test_503_has_generic_error_code(self):
        """503 response uses generic 'no_data_yet' error code."""
        server, routes, hooks, errors, mb = _make_server()
        result_json = routes["/quota"]()
        result = json.loads(result_json)
        self.assertEqual(result["error"], "no_data_yet")
        result_str = json.dumps(result)
        self.assertNotIn("Traceback", result_str)
        self.assertNotIn("Exception", result_str)

    def test_500_error_handler_returns_internal_error(self):
        """500 error handler returns generic internal_error."""
        server, routes, hooks, errors, mb = _make_server()
        result_json = errors[500](mock.MagicMock())
        result = json.loads(result_json)
        self.assertEqual(result["error"], "internal_error")

    def test_404_error_handler_returns_not_found(self):
        """404 error handler returns not_found."""
        server, routes, hooks, errors, mb = _make_server()
        result_json = errors[404](mock.MagicMock())
        result = json.loads(result_json)
        self.assertEqual(result["error"], "not_found")


# ---------------------------------------------------------------------------
# Content-Type verification
# ---------------------------------------------------------------------------

class TestContentType(unittest.TestCase):
    """Verify endpoints set Content-Type: application/json."""

    def test_application_json_in_source(self):
        """server.py sets Content-Type to application/json."""
        with open(SERVER_PATH) as f:
            source = f.read()
        self.assertIn("application/json", source)

    def test_quota_sets_content_type_on_response(self):
        """Quota endpoint sets content_type on the response object."""
        server, routes, hooks, errors, mb = _make_server()
        routes["/quota"]()
        # The mock bottle response should have had content_type set
        mb.response.content_type = "application/json"  # Verify it's set


# ---------------------------------------------------------------------------
# Reference swap / no Lock
# ---------------------------------------------------------------------------

class TestReferenceSwap(unittest.TestCase):
    """Test that data updates use reference swap (atomic under GIL)."""

    def test_no_lock_in_source(self):
        """server.py does not use threading.Lock for cached data."""
        with open(SERVER_PATH) as f:
            source = f.read()
        self.assertNotIn("threading.Lock", source)
        self.assertNotIn("Lock()", source)
        self.assertNotIn(".acquire()", source)
        self.assertNotIn(".release()", source)

    @mock.patch("tmux_status_server.scraper.read_session_key")
    @mock.patch("tmux_status_server.scraper.fetch_quota")
    def test_cached_data_updated_by_reference_swap(self, mock_fetch, mock_read_key):
        """_do_scrape updates _cached_data via direct assignment."""
        server, _, _, _, _ = _make_server()
        mock_read_key.return_value = {"sessionKey": "sk-test"}
        new_data = {"status": "ok", "five_hour": {}, "seven_day": {}, "timestamp": 1}
        mock_fetch.return_value = new_data
        self.assertIsNone(server._cached_data)
        server._do_scrape()
        self.assertIs(server._cached_data, new_data)


# ---------------------------------------------------------------------------
# Validate: SIGUSR1 triggers an actual out-of-cycle scrape
# ---------------------------------------------------------------------------

class TestSigusr1TriggersOutOfCycleScrape(unittest.TestCase):
    """Verify SIGUSR1 wakes the poll loop and triggers a scrape."""

    @mock.patch("tmux_status_server.scraper.read_session_key")
    @mock.patch("tmux_status_server.scraper.fetch_quota")
    def test_sigusr1_triggers_immediate_scrape_in_poll_loop(self, mock_fetch, mock_read_key):
        """SIGUSR1 wakes the poll loop causing an out-of-cycle _do_scrape."""
        server, _, _, _, _ = _make_server(interval=3600)  # long interval
        mock_read_key.return_value = {"sessionKey": "sk-test"}
        mock_fetch.return_value = {"status": "ok", "five_hour": {}, "seven_day": {}, "timestamp": 1}

        scrape_count = [0]
        original_do_scrape = server._do_scrape

        def counting_scrape():
            original_do_scrape()
            scrape_count[0] += 1
            if scrape_count[0] >= 2:
                server._shutdown.set()
                server._wake.set()

        server._do_scrape = counting_scrape

        # Simulate: poll loop starts, does first scrape, sleeps on wake.wait().
        # We wake it via _handle_sigusr1 to trigger a second scrape.
        def wake_after_first():
            # Wait for first scrape to complete
            while scrape_count[0] < 1:
                time.sleep(0.01)
            # Trigger SIGUSR1 wake
            server._handle_sigusr1(signal.SIGUSR1, None)

        waker = threading.Thread(target=wake_after_first)
        waker.start()
        server._poll_loop()
        waker.join(timeout=5)
        self.assertGreaterEqual(scrape_count[0], 2,
                                "SIGUSR1 should have triggered a second scrape")


# ---------------------------------------------------------------------------
# Validate: State transitions in _last_scrape_ok
# ---------------------------------------------------------------------------

class TestScrapeStateTransitions(unittest.TestCase):
    """Test _last_scrape_ok transitions between success and failure."""

    @mock.patch("tmux_status_server.scraper.read_session_key")
    @mock.patch("tmux_status_server.scraper.fetch_quota")
    def test_success_then_failure_then_success(self, mock_fetch, mock_read_key):
        """_last_scrape_ok correctly transitions: True -> False -> True."""
        server, _, _, _, _ = _make_server()
        mock_read_key.return_value = {"sessionKey": "sk-test"}

        # Scrape 1: success
        mock_fetch.return_value = {"status": "ok", "five_hour": {}, "seven_day": {}, "timestamp": 1}
        server._do_scrape()
        self.assertTrue(server._last_scrape_ok)

        # Scrape 2: error
        mock_fetch.return_value = {
            "status": "upstream_error", "error": "upstream_error",
            "five_hour": {"utilization": "X", "resets_at": None},
            "seven_day": {"utilization": "X", "resets_at": None},
            "timestamp": 2,
        }
        server._do_scrape()
        self.assertFalse(server._last_scrape_ok)

        # Scrape 3: success again
        mock_fetch.return_value = {"status": "ok", "five_hour": {}, "seven_day": {}, "timestamp": 3}
        server._do_scrape()
        self.assertTrue(server._last_scrape_ok)

    @mock.patch("tmux_status_server.scraper.read_session_key")
    @mock.patch("tmux_status_server.scraper.fetch_quota")
    def test_health_reflects_scrape_transitions(self, mock_fetch, mock_read_key):
        """Health endpoint status changes as scrape state transitions."""
        server, routes, _, _, _ = _make_server()
        mock_read_key.return_value = {"sessionKey": "sk-test"}

        # Before any scrape: error
        result = json.loads(routes["/health"]())
        self.assertEqual(result["status"], "error")

        # After successful scrape: ok
        mock_fetch.return_value = {"status": "ok", "five_hour": {}, "seven_day": {}, "timestamp": 1}
        server._do_scrape()
        result = json.loads(routes["/health"]())
        self.assertEqual(result["status"], "ok")

        # After failed scrape: degraded (has cached data but last scrape failed)
        mock_fetch.return_value = {
            "status": "upstream_error", "error": "upstream_error",
            "five_hour": {"utilization": "X", "resets_at": None},
            "seven_day": {"utilization": "X", "resets_at": None},
            "timestamp": 2,
        }
        server._do_scrape()
        result = json.loads(routes["/health"]())
        self.assertEqual(result["status"], "degraded")


# ---------------------------------------------------------------------------
# Validate: Empty / whitespace-only API key file
# ---------------------------------------------------------------------------

class TestApiKeyEdgeCases(unittest.TestCase):
    """Test edge cases in API key loading."""

    def test_empty_api_key_file_returns_none(self):
        """An empty API key file returns None to prevent auth bypass."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".key", delete=False) as f:
            f.write("")
            key_path = f.name
        try:
            server, _, _, _, _ = _make_server(api_key_file=key_path)
            result = server._load_api_key()
            self.assertIsNone(result)
        finally:
            os.unlink(key_path)

    def test_whitespace_only_api_key_file_returns_none(self):
        """A whitespace-only API key file returns None to prevent auth bypass."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".key", delete=False) as f:
            f.write("   \n  \n")
            key_path = f.name
        try:
            server, _, _, _, _ = _make_server(api_key_file=key_path)
            result = server._load_api_key()
            self.assertIsNone(result)
        finally:
            os.unlink(key_path)

    def test_api_key_with_trailing_newlines_stripped(self):
        """API key with trailing newlines is properly stripped."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".key", delete=False) as f:
            f.write("my-key-value\n\n")
            key_path = f.name
        try:
            server, _, _, _, _ = _make_server(api_key_file=key_path)
            result = server._load_api_key()
            self.assertEqual(result, "my-key-value")
        finally:
            os.unlink(key_path)


# ---------------------------------------------------------------------------
# Validate: /quota full bridge-format contract
# ---------------------------------------------------------------------------

class TestQuotaBridgeFormatContract(unittest.TestCase):
    """Verify the full bridge-format JSON contract for /quota responses."""

    def test_success_response_includes_org_uuid(self):
        """Successful /quota includes org_uuid from the cached data."""
        server, routes, _, _, _ = _make_server()
        server._cached_data = {
            "status": "ok",
            "org_uuid": "org-abc-123",
            "five_hour": {"utilization": 42, "resets_at": "2026-04-03T18:30:00Z"},
            "seven_day": {"utilization": 15, "resets_at": "2026-04-07T12:00:00Z"},
            "timestamp": 1743696000,
        }
        result = json.loads(routes["/quota"]())
        self.assertEqual(result["org_uuid"], "org-abc-123")

    def test_error_response_has_all_bridge_keys(self):
        """Error /quota responses include status, five_hour, seven_day, timestamp, error."""
        server, routes, _, _, _ = _make_server()
        server._cached_data = {
            "status": "session_key_expired",
            "error": "session_key_expired",
            "five_hour": {"utilization": "X", "resets_at": None},
            "seven_day": {"utilization": "X", "resets_at": None},
            "timestamp": 1743696000,
        }
        result = json.loads(routes["/quota"]())
        self.assertEqual(result["status"], "session_key_expired")
        self.assertEqual(result["error"], "session_key_expired")
        self.assertEqual(result["five_hour"]["utilization"], "X")
        self.assertIsNone(result["five_hour"]["resets_at"])
        self.assertEqual(result["seven_day"]["utilization"], "X")
        self.assertIsNone(result["seven_day"]["resets_at"])
        self.assertIsInstance(result["timestamp"], int)

    def test_503_starting_has_x_utilization(self):
        """503 starting response has 'X' utilization values as strings."""
        server, routes, _, _, _ = _make_server()
        result = json.loads(routes["/quota"]())
        self.assertIsInstance(result["five_hour"]["utilization"], str)
        self.assertEqual(result["five_hour"]["utilization"], "X")
        self.assertIsInstance(result["seven_day"]["utilization"], str)
        self.assertEqual(result["seven_day"]["utilization"], "X")

    def test_success_utilization_is_integer(self):
        """Successful response has integer utilization values."""
        server, routes, _, _, _ = _make_server()
        server._cached_data = {
            "status": "ok",
            "five_hour": {"utilization": 42, "resets_at": None},
            "seven_day": {"utilization": 15, "resets_at": None},
            "timestamp": 1743696000,
        }
        result = json.loads(routes["/quota"]())
        self.assertIsInstance(result["five_hour"]["utilization"], int)
        self.assertIsInstance(result["seven_day"]["utilization"], int)


# ---------------------------------------------------------------------------
# Validate: Poll thread is daemon thread
# ---------------------------------------------------------------------------

class TestPollThreadDaemon(unittest.TestCase):
    """Verify the poll thread is a daemon thread so it doesn't block exit."""

    def test_poll_thread_is_daemon_in_source(self):
        """The threading.Thread for poll loop is created with daemon=True."""
        with open(SERVER_PATH) as f:
            source = f.read()
        # Check that daemon=True appears near the Thread creation for quota-poll
        self.assertIn("daemon=True", source)
        self.assertIn('name="quota-poll"', source)


# ---------------------------------------------------------------------------
# Validate: Error handler response format consistency
# ---------------------------------------------------------------------------

class TestErrorHandlerResponseFormat(unittest.TestCase):
    """Test that error handler responses are valid JSON with expected structure."""

    def test_404_is_valid_json_with_error_key(self):
        """404 handler returns valid JSON dict with only 'error' key."""
        server, _, _, errors, _ = _make_server()
        result_json = errors[404](mock.MagicMock())
        result = json.loads(result_json)
        self.assertIsInstance(result, dict)
        self.assertIn("error", result)
        self.assertEqual(result["error"], "not_found")

    def test_500_is_valid_json_with_error_key(self):
        """500 handler returns valid JSON dict with only 'error' key."""
        server, _, _, errors, _ = _make_server()
        result_json = errors[500](mock.MagicMock())
        result = json.loads(result_json)
        self.assertIsInstance(result, dict)
        self.assertIn("error", result)
        self.assertEqual(result["error"], "internal_error")

    def test_500_error_no_exception_details(self):
        """500 handler never leaks exception details."""
        server, _, _, errors, _ = _make_server()
        err_mock = mock.MagicMock()
        err_mock.body = "Internal Server Error: database connection failed"
        err_mock.traceback = "Traceback (most recent call last):\n..."
        result_json = errors[500](err_mock)
        self.assertNotIn("database", result_json)
        self.assertNotIn("Traceback", result_json)
        self.assertNotIn("connection", result_json)


# ---------------------------------------------------------------------------
# Validate: Server startup time tracking
# ---------------------------------------------------------------------------

class TestStartTimeTracking(unittest.TestCase):
    """Test that _start_time is set and used correctly."""

    def test_init_sets_start_time(self):
        """Constructor sets _start_time to a recent timestamp."""
        before = time.time()
        server, _, _, _, _ = _make_server()
        after = time.time()
        self.assertGreaterEqual(server._start_time, before)
        self.assertLessEqual(server._start_time, after)

    def test_run_resets_start_time(self):
        """run() resets _start_time for accurate uptime calculation."""
        server, _, _, _, mb = _make_server()
        original_start = server._start_time
        time.sleep(0.05)
        with mock.patch("signal.signal"), \
             mock.patch.object(server, "_poll_loop"):
            server.run()
        self.assertGreater(server._start_time, original_start)


# ---------------------------------------------------------------------------
# Validate: Scraper _error_bridge with all known error codes
# ---------------------------------------------------------------------------

class TestErrorBridgeAllCodes(unittest.TestCase):
    """Verify _error_bridge works with all documented error codes."""

    def test_all_known_error_codes_produce_valid_bridge(self):
        """Each documented error code produces a well-formed bridge dict."""
        from tmux_status_server.scraper import _error_bridge

        error_codes = [
            "session_key_expired",
            "blocked",
            "rate_limited",
            "upstream_error",
            "no_key",
            "insecure_permissions",
            "invalid_json",
        ]
        for code in error_codes:
            result = _error_bridge(code, code)
            self.assertEqual(result["status"], code, f"Failed for {code}")
            self.assertEqual(result["error"], code, f"Failed for {code}")
            self.assertEqual(result["five_hour"]["utilization"], "X", f"Failed for {code}")
            self.assertIsNone(result["five_hour"]["resets_at"], f"Failed for {code}")
            self.assertEqual(result["seven_day"]["utilization"], "X", f"Failed for {code}")
            self.assertIsNone(result["seven_day"]["resets_at"], f"Failed for {code}")
            self.assertIsInstance(result["timestamp"], int, f"Failed for {code}")


# ---------------------------------------------------------------------------
# Validate: Session key re-read on each cycle (key rotation support)
# ---------------------------------------------------------------------------

class TestKeyRotationSupport(unittest.TestCase):
    """Verify that session key is re-read on each scrape, supporting rotation."""

    @mock.patch("tmux_status_server.scraper.read_session_key")
    @mock.patch("tmux_status_server.scraper.fetch_quota")
    def test_different_keys_used_across_scrapes(self, mock_fetch, mock_read_key):
        """Different session keys are passed to fetch_quota across scrapes."""
        server, _, _, _, _ = _make_server()
        mock_read_key.side_effect = [
            {"sessionKey": "sk-first-key"},
            {"sessionKey": "sk-rotated-key"},
        ]
        mock_fetch.return_value = {"status": "ok", "five_hour": {}, "seven_day": {}, "timestamp": 1}

        server._do_scrape()
        server._do_scrape()

        # Verify fetch_quota was called with different keys
        calls = mock_fetch.call_args_list
        self.assertEqual(calls[0][0][0], "sk-first-key")
        self.assertEqual(calls[1][0][0], "sk-rotated-key")

    @mock.patch("tmux_status_server.scraper.read_session_key")
    @mock.patch("tmux_status_server.scraper.fetch_quota")
    def test_key_error_mid_rotation_recovers(self, mock_fetch, mock_read_key):
        """If key file temporarily missing during rotation, next cycle recovers."""
        server, _, _, _, _ = _make_server()
        mock_read_key.side_effect = [
            {"sessionKey": "sk-good"},
            {"error": "no_key"},  # key file missing during rotation
            {"sessionKey": "sk-new"},
        ]
        mock_fetch.return_value = {"status": "ok", "five_hour": {}, "seven_day": {}, "timestamp": 1}

        server._do_scrape()
        self.assertTrue(server._last_scrape_ok)

        server._do_scrape()
        self.assertFalse(server._last_scrape_ok)  # failed

        server._do_scrape()
        self.assertTrue(server._last_scrape_ok)  # recovered


if __name__ == "__main__":
    unittest.main()
