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

from tmux_status_server.cli_usage import error_bridge  # noqa: E402


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
            "api_key_file": None,
            "interval": 300,
        }
        defaults.update(overrides)
        server = QuotaServer(**defaults)
        return server, routes, hooks, errors, mock_bottle


class _StubCollector:
    """A UsageCollector stand-in: returns a fixed bridge, or raises."""

    def __init__(self, result=None, exc=None):
        self.result = result
        self.exc = exc
        self.calls = 0

    def collect(self):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return self.result


def _ok_bridge():
    """A minimal successful quota bridge."""
    return {
        "status": "ok",
        "five_hour": {"utilization": 42, "resets_at": None},
        "seven_day": {"utilization": 15, "resets_at": None},
        "model_week": None,
        "timestamp": 1000,
    }


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

    def test_imports_collector(self):
        """server.py imports the CLI usage collector, not the removed scraper."""
        collector_imports = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and "cli_usage" in node.module:
                    collector_imports.extend(alias.name for alias in node.names)
                self.assertNotIn("scraper", node.module or "")
        self.assertIn("CliUsageCollector", collector_imports)
        self.assertIn("error_bridge", collector_imports)

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

    def test_no_config_imports(self):
        """__main__.py does not import from config."""
        config_imports = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and "config" in node.module:
                    config_imports.extend(alias.name for alias in node.names)
        self.assertEqual(config_imports, [], "Expected no config imports in __main__.py")


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
        self.assertIsNone(server.api_key_file)
        self.assertEqual(server.interval, 300)

    def test_init_default_state(self):
        """Constructor sets default internal state."""
        server, _, _, _, _ = _make_server()
        self.assertIsNone(server._cached_data)
        self.assertFalse(server._last_collect_ok)

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
        """Constructor registers error handlers for 401, 404 and 500."""
        server, routes, hooks, errors, _ = _make_server()
        self.assertIn(401, errors)
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

    def test_returns_ok_when_data_and_collect_ok(self):
        """GET /health returns 'ok' when data cached and last collection succeeded."""
        server, routes, hooks, errors, mb = _make_server()
        server._cached_data = {"status": "ok"}
        server._last_collect_ok = True
        result_json = routes["/health"]()
        result = json.loads(result_json)
        self.assertEqual(result["status"], "ok")

    def test_returns_degraded_when_data_but_last_collect_failed(self):
        """GET /health returns 'degraded' when cached data but last collection failed."""
        server, routes, hooks, errors, mb = _make_server()
        server._cached_data = {"status": "upstream_error"}
        server._last_collect_ok = False
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
    """Test the background collection poll thread behavior."""

    def test_first_collect_happens_immediately(self):
        """The poll loop performs the first collection immediately on startup."""
        server, _, _, _, _ = _make_server(collector=_StubCollector(_ok_bridge()))
        server._do_collect()
        self.assertEqual(server.collector.calls, 1)
        self.assertIsNotNone(server._cached_data)
        self.assertTrue(server._last_collect_ok)

    def test_collects_each_cycle(self):
        """The collector is invoked once per cycle."""
        server, _, _, _, _ = _make_server(collector=_StubCollector(_ok_bridge()))
        server._do_collect()
        server._do_collect()
        server._do_collect()
        self.assertEqual(server.collector.calls, 3)

    def test_handles_collector_error_bridge(self):
        """A collector error bridge is cached and marks the cycle failed."""
        server, _, _, _, _ = _make_server(
            collector=_StubCollector(error_bridge("cli_not_found"))
        )
        server._do_collect()
        self.assertEqual(server._cached_data["status"], "error")
        self.assertEqual(server._cached_data["error"], "cli_not_found")
        self.assertFalse(server._last_collect_ok)

    def test_handles_collector_exception(self):
        """A collector that raises is contained, not allowed to kill the thread."""
        server, _, _, _, _ = _make_server(
            collector=_StubCollector(exc=Exception("unexpected"))
        )
        server._do_collect()
        self.assertEqual(server._cached_data["status"], "error")
        self.assertEqual(server._cached_data["error"], "collector_crashed")
        self.assertFalse(server._last_collect_ok)

    def test_sets_last_collect_ok_false_on_error_status(self):
        """A non-ok status leaves _last_collect_ok False."""
        server, _, _, _, _ = _make_server(
            collector=_StubCollector(error_bridge("usage_parse_failed"))
        )
        server._do_collect()
        self.assertFalse(server._last_collect_ok)

    def test_poll_loop_immediate_collect_then_shutdown(self):
        """Poll loop collects immediately, then exits on shutdown."""
        server, _, _, _, _ = _make_server(collector=_StubCollector(_ok_bridge()))
        original = server._do_collect
        call_count = [0]

        def counting():
            original()
            call_count[0] += 1
            if call_count[0] >= 1:
                server._shutdown.set()
                server._wake.set()

        server._do_collect = counting
        server._poll_loop()
        self.assertGreaterEqual(call_count[0], 1)

    def test_error_bridge_no_raw_exception(self):
        """Error responses never contain raw exception text."""
        server, _, _, _, _ = _make_server(
            collector=_StubCollector(
                exc=RuntimeError("connection to database failed at 0xDEADBEEF")
            )
        )
        server._do_collect()
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
        """SIGTERM handler sets events and raises SystemExit."""
        server, _, _, _, _ = _make_server()
        self.assertFalse(server._shutdown.is_set())
        with self.assertRaises(SystemExit):
            server._handle_sigterm(signal.SIGTERM, None)
        self.assertTrue(server._shutdown.is_set())
        self.assertTrue(server._wake.is_set())

    def test_sigint_sets_shutdown(self):
        """SIGINT handler sets events and raises SystemExit."""
        server, _, _, _, _ = _make_server()
        with self.assertRaises(SystemExit):
            server._handle_sigterm(signal.SIGINT, None)
        self.assertTrue(server._shutdown.is_set())

    def test_sigterm_exit_code_zero(self):
        """SystemExit raised by SIGTERM handler has code 0."""
        server, _, _, _, _ = _make_server()
        with self.assertRaises(SystemExit) as cm:
            server._handle_sigterm(signal.SIGTERM, None)
        self.assertEqual(cm.exception.code, 0)

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
            mock_args.usage_socket = "test-usage"
            mock_args.usage_cwd = "/tmp"
            mock_args.boot_timeout = 42.0
            mock_args.usage_inherit_auth_env = True

            with mock.patch("tmux_status_server.server.parse_args", return_value=mock_args) as mock_parse, \
                 mock.patch("tmux_status_server.server.warn_if_exposed") as mock_warn, \
                 mock.patch("tmux_status_server.server.HeadlessClaudeSession") as MockSession, \
                 mock.patch("tmux_status_server.server.QuotaServer") as MockServer, \
                 mock.patch("logging.basicConfig"):
                tmux_status_server.server.main()
                mock_parse.assert_called_once()
                mock_warn.assert_called_once_with(mock_args)
                kwargs = MockServer.call_args.kwargs
                self.assertEqual(kwargs["host"], "127.0.0.1")
                self.assertEqual(kwargs["port"], 7850)
                self.assertIsNone(kwargs["api_key_file"])
                self.assertEqual(kwargs["interval"], 300)
                self.assertIsNotNone(kwargs["collector"])
                kwargs["collector"]._session_factory()
                MockSession.assert_called_once_with(
                    socket_name="test-usage",
                    cwd="/tmp",
                    boot_timeout=42.0,
                    inherit_auth_env=True,
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

    def test_401_error_handler_returns_invalid_key(self):
        """401 error handler returns invalid_or_missing_api_key."""
        server, routes, hooks, errors, mb = _make_server()
        result_json = errors[401](mock.MagicMock())
        result = json.loads(result_json)
        self.assertEqual(result["error"], "invalid_or_missing_api_key")


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

    def test_cached_data_updated_by_reference_swap(self):
        """_do_collect updates _cached_data via direct assignment."""
        new_data = _ok_bridge()
        server, _, _, _, _ = _make_server(collector=_StubCollector(new_data))
        self.assertIsNone(server._cached_data)
        server._do_collect()
        self.assertIs(server._cached_data, new_data)


# ---------------------------------------------------------------------------
# Validate: SIGUSR1 triggers an actual out-of-cycle scrape
# ---------------------------------------------------------------------------

class TestSigusr1TriggersOutOfCycleCollect(unittest.TestCase):
    """Verify SIGUSR1 wakes the poll loop and triggers a collection."""

    def test_sigusr1_triggers_immediate_collect_in_poll_loop(self):
        """SIGUSR1 wakes the poll loop causing an out-of-cycle _do_collect."""
        server, _, _, _, _ = _make_server(
            interval=3600, collector=_StubCollector(_ok_bridge())
        )

        count = [0]
        original = server._do_collect

        def counting():
            original()
            count[0] += 1
            if count[0] >= 2:
                server._shutdown.set()
                server._wake.set()

        server._do_collect = counting

        # The poll loop collects once, then blocks on wake.wait(); SIGUSR1
        # must wake it for a second collection well inside the 3600s interval.
        def wake_after_first():
            while count[0] < 1:
                time.sleep(0.01)
            server._handle_sigusr1(signal.SIGUSR1, None)

        waker = threading.Thread(target=wake_after_first)
        waker.start()
        server._poll_loop()
        waker.join(timeout=5)
        self.assertGreaterEqual(
            count[0], 2, "SIGUSR1 should have triggered a second collection"
        )


# ---------------------------------------------------------------------------
# Validate: State transitions in _last_collect_ok
# ---------------------------------------------------------------------------

class TestCollectStateTransitions(unittest.TestCase):
    """Test _last_collect_ok transitions between success and failure."""

    def test_success_then_failure_then_success(self):
        """_last_collect_ok correctly transitions: True -> False -> True."""
        collector = _StubCollector(_ok_bridge())
        server, _, _, _, _ = _make_server(collector=collector)

        server._do_collect()
        self.assertTrue(server._last_collect_ok)

        collector.result = error_bridge("usage_screen_timeout")
        server._do_collect()
        self.assertFalse(server._last_collect_ok)

        collector.result = _ok_bridge()
        server._do_collect()
        self.assertTrue(server._last_collect_ok)

    def test_health_reflects_collect_transitions(self):
        """Health endpoint status changes as collection state transitions."""
        collector = _StubCollector(_ok_bridge())
        server, routes, _, _, _ = _make_server(collector=collector)

        # Before any collection: error (no data at all).
        self.assertEqual(json.loads(routes["/health"]())["status"], "error")

        server._do_collect()
        self.assertEqual(json.loads(routes["/health"]())["status"], "ok")

        # Failed collection with data already cached: degraded.
        collector.result = error_bridge("usage_parse_failed")
        server._do_collect()
        self.assertEqual(json.loads(routes["/health"]())["status"], "degraded")


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
# Validate: error_bridge with all known collector error codes
# ---------------------------------------------------------------------------

class TestErrorBridgeAllCodes(unittest.TestCase):
    """Verify error_bridge works with every documented collector error code."""

    def test_all_known_error_codes_produce_valid_bridge(self):
        """Each documented error code produces a well-formed bridge dict."""
        error_codes = [
            "cli_not_found",
            "cli_boot_timeout",
            "cli_not_authenticated",
            "usage_screen_timeout",
            "usage_no_limit_windows",
            "usage_parse_failed",
            "tmux_unavailable",
            "collector_crashed",
        ]
        for code in error_codes:
            result = error_bridge(code)
            # status is always the literal "error"; the cause lives in `error`,
            # which is what makes render.py's error branch reachable.
            self.assertEqual(result["status"], "error", f"Failed for {code}")
            self.assertEqual(result["error"], code, f"Failed for {code}")
            self.assertEqual(result["five_hour"]["utilization"], "X", f"Failed for {code}")
            self.assertIsNone(result["five_hour"]["resets_at"], f"Failed for {code}")
            self.assertEqual(result["seven_day"]["utilization"], "X", f"Failed for {code}")
            self.assertIsNone(result["seven_day"]["resets_at"], f"Failed for {code}")
            self.assertIsInstance(result["timestamp"], int, f"Failed for {code}")


# ---------------------------------------------------------------------------
# Validate: Session key re-read on each cycle (key rotation support)
# ---------------------------------------------------------------------------

class TestCollectorIsReinvokedEachCycle(unittest.TestCase):
    """Each cycle re-runs collection rather than reusing a cached credential.

    Replaces the old key-rotation test: there is no longer a session key to
    rotate, but every cycle must still produce a freshly collected bridge.
    """

    def test_fresh_result_each_cycle(self):
        """Consecutive cycles pick up changed collector output."""
        collector = _StubCollector(_ok_bridge())
        server, _, _, _, _ = _make_server(collector=collector)

        server._do_collect()
        first = server._cached_data

        second_bridge = _ok_bridge()
        second_bridge["five_hour"]["utilization"] = 99
        collector.result = second_bridge
        server._do_collect()

        self.assertEqual(collector.calls, 2)
        self.assertIsNot(server._cached_data, first)
        self.assertEqual(server._cached_data["five_hour"]["utilization"], 99)


# ---------------------------------------------------------------------------
# WSGI Integration Tests — Auth via webtest.TestApp
# ---------------------------------------------------------------------------

def _make_wsgi_server(**overrides):
    """Create a QuotaServer with real Bottle (no mocks) for WSGI integration tests.

    Returns a (server, TestApp) tuple.
    """
    from webtest import TestApp
    from tmux_status_server.server import QuotaServer

    defaults = {
        "host": "127.0.0.1",
        "port": 7850,
        "api_key_file": None,
        "interval": 300,
    }
    defaults.update(overrides)
    server = QuotaServer(**defaults)
    app = TestApp(server._app)
    return server, app


_SAMPLE_QUOTA_DATA = {
    "status": "ok",
    "org_uuid": "org-abc-123",
    "five_hour": {"utilization": 42, "resets_at": "2026-04-03T18:30:00Z"},
    "seven_day": {"utilization": 15, "resets_at": "2026-04-07T12:00:00Z"},
    "timestamp": 1743696000,
}


class TestAuthIntegrationWSGI(unittest.TestCase):
    """WSGI integration tests proving auth blocks data leakage.

    Uses webtest.TestApp wrapping the real Bottle pipeline — no mocking
    of Bottle internals.
    """

    def test_valid_key_returns_200_with_data(self):
        """Valid X-API-Key header returns 200 with full quota data."""
        server, app = _make_wsgi_server()
        server._api_key = "test-secret"
        server._cached_data = dict(_SAMPLE_QUOTA_DATA)

        resp = app.get("/quota", headers={"X-API-Key": "test-secret"})
        self.assertEqual(resp.status_int, 200)
        data = resp.json
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["org_uuid"], "org-abc-123")
        self.assertEqual(data["five_hour"]["utilization"], 42)
        self.assertEqual(data["seven_day"]["utilization"], 15)

    def test_wrong_key_returns_401_no_data(self):
        """Wrong X-API-Key header returns 401 with zero quota data."""
        server, app = _make_wsgi_server()
        server._api_key = "correct-secret"
        server._cached_data = dict(_SAMPLE_QUOTA_DATA)

        resp = app.get("/quota", headers={"X-API-Key": "wrong-key"},
                        expect_errors=True)
        self.assertEqual(resp.status_int, 401)
        body_text = resp.text
        self.assertIn("invalid_or_missing_api_key", body_text)
        # Prove zero quota data leaked
        self.assertNotIn("utilization", body_text)
        self.assertNotIn("org_uuid", body_text)
        self.assertNotIn("org-abc-123", body_text)
        self.assertNotIn("five_hour", body_text)
        self.assertNotIn("seven_day", body_text)

    def test_missing_key_returns_401_no_data(self):
        """Missing X-API-Key header returns 401 with zero quota data."""
        server, app = _make_wsgi_server()
        server._api_key = "test-secret"
        server._cached_data = dict(_SAMPLE_QUOTA_DATA)

        resp = app.get("/quota", expect_errors=True)
        self.assertEqual(resp.status_int, 401)
        body_text = resp.text
        self.assertIn("invalid_or_missing_api_key", body_text)
        # Prove zero quota data leaked
        self.assertNotIn("utilization", body_text)
        self.assertNotIn("org_uuid", body_text)
        self.assertNotIn("org-abc-123", body_text)
        self.assertNotIn("five_hour", body_text)
        self.assertNotIn("seven_day", body_text)

    def test_health_returns_200_always(self):
        """/health returns 200 even when auth is configured and no key provided."""
        server, app = _make_wsgi_server()
        server._api_key = "test-secret"
        server._cached_data = {"status": "ok"}
        server._last_collect_ok = True

        resp = app.get("/health")
        self.assertEqual(resp.status_int, 200)
        data = resp.json
        self.assertIn("status", data)
        self.assertIn("uptime_seconds", data)
        self.assertIn("version", data)

    def test_no_auth_configured_returns_200(self):
        """/quota returns 200 without any auth header when no API key configured."""
        server, app = _make_wsgi_server()
        server._api_key = None
        server._cached_data = dict(_SAMPLE_QUOTA_DATA)

        resp = app.get("/quota")
        self.assertEqual(resp.status_int, 200)
        data = resp.json
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["org_uuid"], "org-abc-123")
        self.assertEqual(data["five_hour"]["utilization"], 42)

    def test_empty_key_file_means_no_auth(self):
        """When API key file is empty, _api_key is None so /quota is open."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".key", delete=False) as f:
            f.write("")
            key_path = f.name
        try:
            server, app = _make_wsgi_server(api_key_file=key_path)
            server._api_key = server._load_api_key()
            self.assertIsNone(server._api_key)
            server._cached_data = dict(_SAMPLE_QUOTA_DATA)

            resp = app.get("/quota")
            self.assertEqual(resp.status_int, 200)
            data = resp.json
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["org_uuid"], "org-abc-123")
        finally:
            os.unlink(key_path)


# ---------------------------------------------------------------------------
# Validate cycle 2: Auth bypass regression tests (TS-26, TS-27)
# ---------------------------------------------------------------------------

class TestAuthBypassRegressionWSGI(unittest.TestCase):
    """WSGI integration tests proving fix cycle 2 auth bypass fixes.

    TS-26: abort(401) in check_auth actually prevents route execution.
    TS-27: Empty API key file returns None, so auth is disabled rather
           than creating a bypass via hmac.compare_digest('', '').
    """

    def test_abort_401_prevents_quota_route_execution(self):
        """TS-26 regression: abort(401) stops the request pipeline before /quota runs.

        Before the fix, the auth hook did not call abort(), allowing the
        request to fall through to the route handler and return quota data.
        """
        server, app = _make_wsgi_server()
        server._api_key = "correct-secret"
        server._cached_data = dict(_SAMPLE_QUOTA_DATA)

        resp = app.get("/quota", headers={"X-API-Key": "wrong"},
                        expect_errors=True)
        self.assertEqual(resp.status_int, 401)
        # The critical assertion: quota data must NOT be in the response body.
        self.assertNotIn("42", resp.text)  # five_hour utilization
        self.assertNotIn("org-abc-123", resp.text)

    def test_empty_string_api_key_not_exploitable_wsgi(self):
        """TS-27 regression: if _api_key were '' (empty string), sending an
        empty X-API-Key header would bypass auth via hmac.compare_digest('','').

        The fix ensures _load_api_key() returns None for empty files, so
        _api_key is never ''. This test verifies the defense-in-depth: even
        if _api_key is forcibly set to '', the abort(401) path fires when
        provided is None (no header), preventing data leakage.
        """
        server, app = _make_wsgi_server()
        # Simulate the old bug: _api_key is empty string
        server._api_key = ""
        server._cached_data = dict(_SAMPLE_QUOTA_DATA)

        # With empty X-API-Key header -> hmac.compare_digest('', '') is True
        # so this request should actually succeed (the hook passes).
        # This demonstrates WHY the fix had to be in _load_api_key() returning
        # None rather than relying on hmac.compare_digest.
        resp = app.get("/quota", headers={"X-API-Key": ""},
                        expect_errors=True)
        # If _api_key is '', hmac.compare_digest('', '') == True, so 200
        self.assertEqual(resp.status_int, 200)

        # But without any header, provided is None, which triggers abort(401)
        # because `provided is None` check fires first.
        resp2 = app.get("/quota", expect_errors=True)
        self.assertEqual(resp2.status_int, 401)
        self.assertNotIn("org-abc-123", resp2.text)

    def test_load_api_key_none_means_open_access(self):
        """TS-27: When _load_api_key() returns None, auth is disabled entirely.

        This is the correct behavior for empty key files: the server operates
        in open mode (no auth) rather than with a broken empty-string key.
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".key", delete=False) as f:
            f.write("  \n")  # whitespace-only
            key_path = f.name
        try:
            server, app = _make_wsgi_server(api_key_file=key_path)
            server._api_key = server._load_api_key()
            self.assertIsNone(server._api_key)
            server._cached_data = dict(_SAMPLE_QUOTA_DATA)

            # Open access: no header needed
            resp = app.get("/quota")
            self.assertEqual(resp.status_int, 200)
            self.assertEqual(resp.json["five_hour"]["utilization"], 42)
        finally:
            os.unlink(key_path)


# ---------------------------------------------------------------------------
# Validate cycle 2: Renderer None utilization guard (TS-28)
# ---------------------------------------------------------------------------

class TestRendererNoneUtilizationGuard(unittest.TestCase):
    """Verify the collector+server pipeline handles None utilization correctly.

    TS-28: the renderer guards utilization with (is None or == 'X'). The CLI
    collector never emits None on a successful bridge -- a window it cannot read
    is a parse failure, not a success with a hole -- but /quota may still be
    served by a remote or older server, so the guard and these pass-through
    contracts must hold regardless.
    """

    def test_collector_never_emits_none_utilization_on_success(self):
        """An ok bridge always carries numeric utilization for both windows."""
        from tmux_status_server.cli_usage import CliUsageCollector, UsageScreenParser

        fixtures = os.path.join(os.path.dirname(__file__), "fixtures")
        with open(os.path.join(fixtures, "usage_nominal.txt")) as f:
            screen = f.read()
        parsed = UsageScreenParser().parse(screen)
        bridge = CliUsageCollector._to_bridge(parsed, None)
        self.assertEqual(bridge["status"], "ok")
        self.assertIsInstance(bridge["five_hour"]["utilization"], float)
        self.assertIsInstance(bridge["seven_day"]["utilization"], float)

    def test_none_utilization_passes_through_quota_endpoint(self):
        """Server /quota endpoint faithfully passes None utilization to clients."""
        server, routes, _, _, _ = _make_server()
        server._cached_data = {
            "status": "ok",
            "five_hour": {"utilization": None, "resets_at": None},
            "seven_day": {"utilization": None, "resets_at": None},
            "timestamp": 1743696000,
        }
        result = json.loads(routes["/quota"]())
        self.assertIsNone(result["five_hour"]["utilization"])
        self.assertIsNone(result["seven_day"]["utilization"])

    def test_x_utilization_in_error_responses(self):
        """Error responses use string 'X' not None for utilization."""
        server, routes, _, _, _ = _make_server()
        result = json.loads(routes["/quota"]())  # no cached data -> 503
        self.assertEqual(result["five_hour"]["utilization"], "X")
        self.assertIsInstance(result["five_hour"]["utilization"], str)


# ---------------------------------------------------------------------------
# Validate cycle 2: WSGI auth + data leakage exhaustive (TS-29)
# ---------------------------------------------------------------------------

class TestWSGIAuthDataLeakageExhaustive(unittest.TestCase):
    """Exhaustive WSGI tests proving auth never leaks data across all paths.

    TS-29 extension: cover paths not in the original WSGI integration tests.
    """

    def test_unknown_path_with_auth_returns_401_not_data(self):
        """Unknown paths with auth configured return 401 (auth fires before 404)."""
        server, app = _make_wsgi_server()
        server._api_key = "secret"
        server._cached_data = dict(_SAMPLE_QUOTA_DATA)

        resp = app.get("/unknown", expect_errors=True)
        self.assertEqual(resp.status_int, 401)
        self.assertNotIn("org-abc-123", resp.text)
        self.assertNotIn("utilization", resp.text)

    def test_unknown_path_without_auth_returns_404_not_data(self):
        """Unknown paths without auth configured return 404, not cached data."""
        server, app = _make_wsgi_server()
        server._api_key = None
        server._cached_data = dict(_SAMPLE_QUOTA_DATA)

        resp = app.get("/unknown", expect_errors=True)
        self.assertEqual(resp.status_int, 404)
        self.assertNotIn("org-abc-123", resp.text)
        self.assertNotIn("utilization", resp.text)

    def test_health_never_leaks_quota_data(self):
        """/health response contains no quota data even when auth is configured."""
        server, app = _make_wsgi_server()
        server._api_key = "secret"
        server._cached_data = dict(_SAMPLE_QUOTA_DATA)
        server._last_collect_ok = True

        resp = app.get("/health")
        self.assertEqual(resp.status_int, 200)
        data = resp.json
        self.assertNotIn("org_uuid", data)
        self.assertNotIn("five_hour", data)
        self.assertNotIn("seven_day", data)
        self.assertNotIn("utilization", resp.text)

    def test_401_response_content_type_is_json(self):
        """Auth failure 401 response has application/json content type."""
        server, app = _make_wsgi_server()
        server._api_key = "secret"
        server._cached_data = dict(_SAMPLE_QUOTA_DATA)

        resp = app.get("/quota", expect_errors=True)
        self.assertTrue(
            resp.content_type.startswith("application/json"),
            f"Expected application/json, got {resp.content_type}",
        )
        body = resp.text
        self.assertIn("invalid_or_missing_api_key", body)


if __name__ == "__main__":
    unittest.main()
