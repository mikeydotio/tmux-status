"""Tests for tmux_status_server.scraper module."""

import ast
import json
import os
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock

# Add server directory to path so we can import the module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tmux_status_server import scraper
from tmux_status_server.scraper import (
    REQUEST_HEADERS,
    _error_bridge,
    fetch_quota,
    read_session_key,
)


class TestReadSessionKey(unittest.TestCase):
    """Test session key file reading and validation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.key_path = os.path.join(self.tmpdir, "claude-usage-key.json")

    def tearDown(self):
        if os.path.exists(self.key_path):
            os.chmod(self.key_path, 0o600)
            os.remove(self.key_path)
        os.rmdir(self.tmpdir)

    def _write_key_file(self, data, mode=0o600):
        with open(self.key_path, "w") as f:
            json.dump(data, f)
        os.chmod(self.key_path, mode)

    def test_valid_key_file(self):
        """Reads a valid session key file with sessionKey and expiresAt."""
        self._write_key_file({
            "sessionKey": "sk-ant-test123",
            "expiresAt": "2026-04-13T21:06:09.521Z",
        })
        result = read_session_key(self.key_path)
        self.assertEqual(result["sessionKey"], "sk-ant-test123")
        self.assertEqual(result["expiresAt"], "2026-04-13T21:06:09.521Z")
        self.assertNotIn("error", result)

    def test_valid_key_file_without_expires(self):
        """Reads a valid session key file that has no expiresAt field."""
        self._write_key_file({"sessionKey": "sk-ant-test456"})
        result = read_session_key(self.key_path)
        self.assertEqual(result["sessionKey"], "sk-ant-test456")
        self.assertNotIn("expiresAt", result)
        self.assertNotIn("error", result)

    def test_missing_file(self):
        """Returns error dict when the file does not exist."""
        result = read_session_key("/nonexistent/path/key.json")
        self.assertEqual(result["error"], "no_key")

    def test_bad_permissions_group_readable(self):
        """Returns error when file is group-readable (0o640)."""
        self._write_key_file({"sessionKey": "sk-ant-test"}, mode=0o640)
        result = read_session_key(self.key_path)
        self.assertEqual(result["error"], "insecure_permissions")

    def test_bad_permissions_other_readable(self):
        """Returns error when file is other-readable (0o604)."""
        self._write_key_file({"sessionKey": "sk-ant-test"}, mode=0o604)
        result = read_session_key(self.key_path)
        self.assertEqual(result["error"], "insecure_permissions")

    def test_bad_permissions_world_readable(self):
        """Returns error when file is world-readable (0o644)."""
        self._write_key_file({"sessionKey": "sk-ant-test"}, mode=0o644)
        result = read_session_key(self.key_path)
        self.assertEqual(result["error"], "insecure_permissions")

    def test_owner_only_permissions_pass(self):
        """Accepts file with owner-only permissions (0o600)."""
        self._write_key_file({"sessionKey": "sk-ant-test"}, mode=0o600)
        result = read_session_key(self.key_path)
        self.assertEqual(result["sessionKey"], "sk-ant-test")
        self.assertNotIn("error", result)

    def test_owner_read_only_permissions_pass(self):
        """Accepts file with owner read-only permissions (0o400)."""
        self._write_key_file({"sessionKey": "sk-ant-test"}, mode=0o400)
        result = read_session_key(self.key_path)
        self.assertEqual(result["sessionKey"], "sk-ant-test")
        self.assertNotIn("error", result)

    def test_invalid_json(self):
        """Returns error when file contains invalid JSON."""
        with open(self.key_path, "w") as f:
            f.write("not valid json {{{")
        os.chmod(self.key_path, 0o600)
        result = read_session_key(self.key_path)
        self.assertEqual(result["error"], "invalid_json")

    def test_json_without_session_key(self):
        """Returns error when JSON is valid but missing sessionKey."""
        self._write_key_file({"someOtherField": "value"})
        result = read_session_key(self.key_path)
        self.assertEqual(result["error"], "invalid_json")

    def test_json_array_instead_of_object(self):
        """Returns error when JSON is a list instead of a dict."""
        with open(self.key_path, "w") as f:
            json.dump(["not", "a", "dict"], f)
        os.chmod(self.key_path, 0o600)
        result = read_session_key(self.key_path)
        self.assertEqual(result["error"], "invalid_json")

    def test_no_raw_exception_text(self):
        """Error dicts must never contain raw exception text."""
        # Missing file
        result = read_session_key("/nonexistent/path")
        for value in result.values():
            if isinstance(value, str):
                self.assertNotIn("Traceback", value)
                self.assertNotIn("Error", value)
                self.assertNotIn("errno", value.lower())

        # Bad JSON
        with open(self.key_path, "w") as f:
            f.write("{bad json")
        os.chmod(self.key_path, 0o600)
        result = read_session_key(self.key_path)
        for value in result.values():
            if isinstance(value, str):
                self.assertNotIn("Traceback", value)
                self.assertNotIn("JSONDecodeError", value)


class TestFetchQuota(unittest.TestCase):
    """Test quota fetching with mocked HTTP."""

    def setUp(self):
        # Reset module-level org UUID cache before each test.
        scraper._org_uuid = None

    def _mock_http_get(self, responses):
        """Create a side_effect function for _http_get that returns
        different responses for different URLs.

        Args:
            responses: dict mapping URL suffixes to (status, body) tuples.
                       Matched by checking if the URL ends with the pattern.
        """
        def side_effect(url, session_key):
            for pattern, response in responses.items():
                if url.endswith(pattern):
                    return response
            return (500, None)
        return side_effect

    @mock.patch("tmux_status_server.scraper._http_get")
    def test_success(self, mock_get):
        """Successful quota fetch returns bridge-format dict."""
        mock_get.side_effect = self._mock_http_get({
            "/organizations": (200, [{"uuid": "org-123-abc"}]),
            "/usage": (200, {
                "five_hour": {"utilization": 42, "resets_at": "2026-04-03T18:30:00Z"},
                "seven_day": {"utilization": 15, "resets_at": "2026-04-07T12:00:00Z"},
            }),
        })

        result = fetch_quota("sk-ant-test")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result.get("org_uuid"), "org-123-abc")
        self.assertEqual(result["five_hour"]["utilization"], 42)
        self.assertEqual(result["five_hour"]["resets_at"], "2026-04-03T18:30:00Z")
        self.assertEqual(result["seven_day"]["utilization"], 15)
        self.assertEqual(result["seven_day"]["resets_at"], "2026-04-07T12:00:00Z")
        self.assertIn("timestamp", result)
        self.assertIsInstance(result["timestamp"], int)
        self.assertNotIn("error", result)

    @mock.patch("tmux_status_server.scraper._http_get")
    def test_http_401_maps_to_session_key_expired(self, mock_get):
        """HTTP 401 on org discovery maps to session_key_expired."""
        mock_get.return_value = (401, None)
        result = fetch_quota("sk-ant-expired")
        self.assertEqual(result["status"], "session_key_expired")
        self.assertEqual(result["error"], "session_key_expired")
        self.assertEqual(result["five_hour"]["utilization"], "X")
        self.assertIsNone(result["five_hour"]["resets_at"])
        self.assertEqual(result["seven_day"]["utilization"], "X")
        self.assertIsNone(result["seven_day"]["resets_at"])

    @mock.patch("tmux_status_server.scraper._http_get")
    def test_http_403_maps_to_blocked(self, mock_get):
        """HTTP 403 maps to blocked error."""
        mock_get.return_value = (403, None)
        result = fetch_quota("sk-ant-blocked")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["error"], "blocked")
        self.assertEqual(result["five_hour"]["utilization"], "X")
        self.assertEqual(result["seven_day"]["utilization"], "X")

    @mock.patch("tmux_status_server.scraper._http_get")
    def test_http_429_maps_to_rate_limited(self, mock_get):
        """HTTP 429 maps to rate_limited error."""
        mock_get.return_value = (429, None)
        result = fetch_quota("sk-ant-throttled")
        self.assertEqual(result["status"], "rate_limited")
        self.assertEqual(result["error"], "rate_limited")
        self.assertEqual(result["five_hour"]["utilization"], "X")
        self.assertEqual(result["seven_day"]["utilization"], "X")

    @mock.patch("tmux_status_server.scraper._http_get")
    def test_http_401_on_usage_endpoint(self, mock_get):
        """HTTP 401 on usage endpoint (after successful org discovery)."""
        mock_get.side_effect = self._mock_http_get({
            "/organizations": (200, [{"uuid": "org-123"}]),
            "/usage": (401, None),
        })
        result = fetch_quota("sk-ant-test")
        self.assertEqual(result["status"], "session_key_expired")
        self.assertEqual(result["error"], "session_key_expired")

    @mock.patch("tmux_status_server.scraper._http_get")
    def test_http_500_maps_to_upstream_error(self, mock_get):
        """Unexpected HTTP status codes map to upstream_error."""
        mock_get.return_value = (500, None)
        result = fetch_quota("sk-ant-test")
        self.assertEqual(result["status"], "upstream_error")
        self.assertEqual(result["error"], "upstream_error")

    @mock.patch("tmux_status_server.scraper._http_get")
    def test_network_error_returns_upstream_error(self, mock_get):
        """Network exceptions produce upstream_error."""
        mock_get.side_effect = ConnectionError("network down")
        result = fetch_quota("sk-ant-test")
        self.assertEqual(result["status"], "upstream_error")
        self.assertEqual(result["error"], "upstream_error")
        self.assertEqual(result["five_hour"]["utilization"], "X")
        self.assertEqual(result["seven_day"]["utilization"], "X")

    @mock.patch("tmux_status_server.scraper._http_get")
    def test_timeout_error_returns_upstream_error(self, mock_get):
        """Timeout exceptions produce upstream_error."""
        mock_get.side_effect = TimeoutError("timed out")
        result = fetch_quota("sk-ant-test")
        self.assertEqual(result["status"], "upstream_error")
        self.assertEqual(result["error"], "upstream_error")

    @mock.patch("tmux_status_server.scraper._http_get")
    def test_empty_org_list_returns_upstream_error(self, mock_get):
        """Empty organizations list returns upstream_error."""
        mock_get.return_value = (200, [])
        result = fetch_quota("sk-ant-test")
        self.assertEqual(result["status"], "upstream_error")
        self.assertEqual(result["error"], "upstream_error")

    @mock.patch("tmux_status_server.scraper._http_get")
    def test_non_list_org_response_returns_upstream_error(self, mock_get):
        """Non-list organizations response returns upstream_error."""
        mock_get.return_value = (200, {"error": "something"})
        result = fetch_quota("sk-ant-test")
        self.assertEqual(result["status"], "upstream_error")
        self.assertEqual(result["error"], "upstream_error")


class TestOrgUuidCaching(unittest.TestCase):
    """Test that org UUID is cached at module level."""

    def setUp(self):
        scraper._org_uuid = None

    @mock.patch("tmux_status_server.scraper._http_get")
    def test_org_uuid_cached_after_first_call(self, mock_get):
        """Org UUID is stored in module-level _org_uuid after first call."""
        mock_get.side_effect = [
            (200, [{"uuid": "org-cached-123"}]),
            (200, {
                "five_hour": {"utilization": 10, "resets_at": None},
                "seven_day": {"utilization": 5, "resets_at": None},
            }),
        ]
        fetch_quota("sk-ant-test")
        self.assertEqual(scraper._org_uuid, "org-cached-123")

    @mock.patch("tmux_status_server.scraper._http_get")
    def test_cached_org_uuid_skips_org_discovery(self, mock_get):
        """When _org_uuid is set, org discovery API call is skipped."""
        scraper._org_uuid = "org-pre-cached"
        mock_get.return_value = (200, {
            "five_hour": {"utilization": 20, "resets_at": None},
            "seven_day": {"utilization": 8, "resets_at": None},
        })

        result = fetch_quota("sk-ant-test")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["org_uuid"], "org-pre-cached")
        # Should only have called _http_get once (usage, not orgs)
        self.assertEqual(mock_get.call_count, 1)
        call_url = mock_get.call_args[0][0]
        self.assertIn("/usage", call_url)
        # The URL will contain /organizations/{uuid}/usage — but it should
        # NOT be the bare /organizations endpoint (which ends without /usage).
        self.assertFalse(
            call_url.endswith("/organizations"),
            "Should not call the org discovery endpoint when UUID is cached",
        )

    @mock.patch("tmux_status_server.scraper._http_get")
    def test_org_uuid_discovered_then_reused(self, mock_get):
        """Two sequential calls: first discovers org, second reuses cache."""
        usage_response = (200, {
            "five_hour": {"utilization": 30, "resets_at": None},
            "seven_day": {"utilization": 12, "resets_at": None},
        })
        mock_get.side_effect = [
            # First call: org discovery + usage
            (200, [{"uuid": "org-reuse-test"}]),
            usage_response,
            # Second call: usage only (org cached)
            usage_response,
        ]

        fetch_quota("sk-ant-test")
        fetch_quota("sk-ant-test")

        # 3 calls total: orgs + usage + usage (no second org discovery)
        self.assertEqual(mock_get.call_count, 3)
        urls = [call[0][0] for call in mock_get.call_args_list]
        org_calls = [u for u in urls if "/organizations" in u and "/usage" not in u]
        self.assertEqual(len(org_calls), 1)


class TestRequestHeaders(unittest.TestCase):
    """Test that REQUEST_HEADERS matches expected values."""

    def test_headers_is_dict(self):
        """REQUEST_HEADERS is a dict."""
        self.assertIsInstance(REQUEST_HEADERS, dict)

    def test_required_header_keys(self):
        """All expected header keys are present."""
        expected_keys = {
            "Accept",
            "Accept-Language",
            "Content-Type",
            "anthropic-client-platform",
            "anthropic-client-version",
            "Origin",
            "Referer",
            "Sec-Fetch-Dest",
            "Sec-Fetch-Mode",
            "Sec-Fetch-Site",
        }
        self.assertEqual(set(REQUEST_HEADERS.keys()), expected_keys)

    def test_header_values(self):
        """Header values match the canonical scraper."""
        self.assertEqual(REQUEST_HEADERS["Accept"], "*/*")
        self.assertEqual(REQUEST_HEADERS["Accept-Language"], "en-US,en;q=0.9")
        self.assertEqual(REQUEST_HEADERS["Content-Type"], "application/json")
        self.assertEqual(REQUEST_HEADERS["anthropic-client-platform"], "web_claude_ai")
        self.assertEqual(REQUEST_HEADERS["anthropic-client-version"], "1.0.0")
        self.assertEqual(REQUEST_HEADERS["Origin"], "https://claude.ai")
        self.assertEqual(REQUEST_HEADERS["Referer"], "https://claude.ai/settings/usage")
        self.assertEqual(REQUEST_HEADERS["Sec-Fetch-Dest"], "empty")
        self.assertEqual(REQUEST_HEADERS["Sec-Fetch-Mode"], "cors")
        self.assertEqual(REQUEST_HEADERS["Sec-Fetch-Site"], "same-origin")


class TestNoRawExceptionTextInErrors(unittest.TestCase):
    """Verify error dicts never contain raw exception text."""

    def setUp(self):
        scraper._org_uuid = None

    @mock.patch("tmux_status_server.scraper._http_get")
    def test_network_error_no_exception_text(self, mock_get):
        """Network error dicts contain no exception messages."""
        mock_get.side_effect = ConnectionError(
            "Connection refused: [Errno 111] detailed system error"
        )
        result = fetch_quota("sk-ant-test")
        result_str = json.dumps(result)
        self.assertNotIn("Connection refused", result_str)
        self.assertNotIn("Errno", result_str)
        self.assertNotIn("Traceback", result_str)

    @mock.patch("tmux_status_server.scraper._http_get")
    def test_type_error_no_exception_text(self, mock_get):
        """TypeError in response parsing contains no exception text."""
        mock_get.side_effect = TypeError("'NoneType' object is not subscriptable")
        result = fetch_quota("sk-ant-test")
        result_str = json.dumps(result)
        self.assertNotIn("NoneType", result_str)
        self.assertNotIn("subscriptable", result_str)

    @mock.patch("tmux_status_server.scraper._http_get")
    def test_all_error_statuses_have_clean_codes(self, mock_get):
        """All HTTP error statuses produce clean error codes, not messages."""
        valid_error_codes = {
            "session_key_expired",
            "blocked",
            "rate_limited",
            "upstream_error",
            "no_key",
        }
        for http_status in [401, 403, 429, 500, 502, 503]:
            scraper._org_uuid = None
            mock_get.return_value = (http_status, None)
            result = fetch_quota("sk-ant-test")
            self.assertIn(result["error"], valid_error_codes,
                          f"HTTP {http_status} produced unexpected error code: {result['error']}")


class TestErrorBridge(unittest.TestCase):
    """Test the _error_bridge helper."""

    def test_error_bridge_structure(self):
        """_error_bridge produces the correct structure."""
        result = _error_bridge("blocked", "blocked")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["error"], "blocked")
        self.assertEqual(result["five_hour"]["utilization"], "X")
        self.assertIsNone(result["five_hour"]["resets_at"])
        self.assertEqual(result["seven_day"]["utilization"], "X")
        self.assertIsNone(result["seven_day"]["resets_at"])
        self.assertIn("timestamp", result)
        self.assertIsInstance(result["timestamp"], int)

    def test_error_bridge_timestamp_is_recent(self):
        """_error_bridge timestamp is close to current time."""
        before = int(time.time())
        result = _error_bridge("test", "test")
        after = int(time.time())
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)


class TestImportVerification(unittest.TestCase):
    """Verify the module imports only allowed external packages."""

    def test_only_curl_cffi_external_import(self):
        """scraper.py imports only curl_cffi as an external package (no bottle, no urllib)."""
        scraper_path = os.path.join(
            os.path.dirname(__file__), "..", "tmux_status_server", "scraper.py"
        )
        with open(scraper_path) as f:
            tree = ast.parse(f.read())

        # stdlib modules that are allowed
        stdlib_modules = {
            "json", "logging", "os", "stat", "time", "sys", "pathlib",
        }
        # The only allowed external package
        allowed_external = {"curl_cffi"}

        forbidden_modules = {"bottle", "urllib", "urllib3", "requests", "httpx"}

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    self.assertNotIn(
                        top, forbidden_modules,
                        f"Forbidden import found: {alias.name}"
                    )
                    self.assertTrue(
                        top in stdlib_modules or top in allowed_external,
                        f"Unexpected import: {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top = node.module.split(".")[0]
                    self.assertNotIn(
                        top, forbidden_modules,
                        f"Forbidden import found: {node.module}"
                    )
                    self.assertTrue(
                        top in stdlib_modules or top in allowed_external,
                        f"Unexpected import: {node.module}"
                    )

    def test_no_bottle_import(self):
        """Module does not import bottle."""
        scraper_path = os.path.join(
            os.path.dirname(__file__), "..", "tmux_status_server", "scraper.py"
        )
        with open(scraper_path) as f:
            source = f.read()
        self.assertNotIn("import bottle", source)
        self.assertNotIn("from bottle", source)

    def test_no_urllib_import(self):
        """Module does not import urllib."""
        scraper_path = os.path.join(
            os.path.dirname(__file__), "..", "tmux_status_server", "scraper.py"
        )
        with open(scraper_path) as f:
            source = f.read()
        # Check for urllib as a standalone import (not within "curl_cffi" context)
        lines = source.split("\n")
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "urllib" in stripped:
                self.fail(f"urllib reference found: {stripped}")


if __name__ == "__main__":
    unittest.main()
