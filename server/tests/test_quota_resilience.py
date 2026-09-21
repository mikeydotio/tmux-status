"""Tests for server-side quota degradation behaviour (TS-56).

Two outages (2026-09-08 ``cli_boot_timeout``, 2026-09-16 ``cli_not_authenticated``)
both rendered an identical bare ``X`` for hours because ``_do_collect`` replaced
the last good reading with the error bridge. These tests pin the replacement
contract: the last good reading survives, it carries its age, and the collector
stops re-booting the CLI at full rate once the failure is clearly sustained.

See ``docs/spec/quota-resilience.md``.
"""

import json
import logging
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tmux_status_server.cli_usage import error_bridge  # noqa: E402

from test_server import _make_server, _ok_bridge, _StubCollector  # noqa: E402


# ── Server: last-known-good retention ──────────────────────────────────────
class TestLastKnownGoodRetention(unittest.TestCase):
    """A failed collection must not destroy the previous good reading."""

    def test_failure_retains_previous_good_reading(self):
        server, _, _, _, _ = _make_server(collector=_StubCollector(_ok_bridge()))
        server._do_collect()
        server.collector.result = error_bridge("cli_not_authenticated")
        server._do_collect()

        self.assertIsNotNone(server._cached_data)
        self.assertEqual(server._cached_data["five_hour"]["utilization"], 42)
        self.assertEqual(server._last_error, "cli_not_authenticated")
        self.assertFalse(server._last_collect_ok)

    def test_failure_before_any_success_leaves_no_good_data(self):
        server, _, _, _, _ = _make_server(
            collector=_StubCollector(error_bridge("cli_not_found"))
        )
        server._do_collect()
        self.assertIsNone(server._cached_data)
        self.assertEqual(server._last_error, "cli_not_found")

    def test_collector_exception_retains_previous_good_reading(self):
        server, _, _, _, _ = _make_server(collector=_StubCollector(_ok_bridge()))
        server._do_collect()
        server.collector.exc = Exception("unexpected")
        server._do_collect()

        self.assertEqual(server._cached_data["five_hour"]["utilization"], 42)
        self.assertEqual(server._last_error, "collector_crashed")

    def test_success_after_failure_restores_ok(self):
        server, _, _, _, _ = _make_server(
            collector=_StubCollector(error_bridge("cli_boot_timeout"))
        )
        server._do_collect()
        server.collector.result = _ok_bridge()
        server._do_collect()

        self.assertTrue(server._last_collect_ok)
        self.assertIsNone(server._last_error)
        self.assertEqual(server._current_bridge()["status"], "ok")


class TestServedBridgeStatus(unittest.TestCase):
    """``/quota`` reports fresh / stale / blind distinctly, always with an age."""

    def test_serves_ok_while_fresh(self):
        server, routes, _, _, _ = _make_server(
            collector=_StubCollector(_ok_bridge())
        )
        server._do_collect()
        result = json.loads(routes["/quota"]())
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["five_hour"]["utilization"], 42)
        self.assertIn("age_seconds", result)

    def test_serves_stale_numbers_with_age_after_failure(self):
        server, routes, _, _, _ = _make_server(
            collector=_StubCollector(_ok_bridge()), fresh_max=60, good_max=86400
        )
        server._do_collect()
        server._cached_at = time.time() - 600
        server.collector.result = error_bridge("cli_not_authenticated")
        server._do_collect()

        result = json.loads(routes["/quota"]())
        self.assertEqual(result["status"], "stale")
        self.assertEqual(result["five_hour"]["utilization"], 42)
        self.assertEqual(result["error"], "cli_not_authenticated")
        self.assertGreaterEqual(result["age_seconds"], 600)

    def test_drops_numbers_once_last_good_exceeds_good_max(self):
        server, routes, _, _, _ = _make_server(
            collector=_StubCollector(_ok_bridge()), fresh_max=60, good_max=3600
        )
        server._do_collect()
        server._cached_at = time.time() - 7200
        server.collector.result = error_bridge("cli_not_authenticated")
        server._do_collect()

        result = json.loads(routes["/quota"]())
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["five_hour"]["utilization"], "X")
        self.assertEqual(result["error"], "cli_not_authenticated")
        self.assertGreaterEqual(result["age_seconds"], 7200)

    def test_reports_failure_code_before_any_success(self):
        server, routes, _, _, _ = _make_server(
            collector=_StubCollector(error_bridge("cli_not_authenticated"))
        )
        server._do_collect()
        result = json.loads(routes["/quota"]())
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"], "cli_not_authenticated")


class TestBackoff(unittest.TestCase):
    """Sustained identical failures must stop re-booting the CLI at full rate."""

    def test_interval_doubles_on_consecutive_failures(self):
        server, _, _, _, _ = _make_server(
            collector=_StubCollector(error_bridge("cli_boot_timeout")),
            interval=300, backoff_max=3600,
        )
        self.assertEqual(server._next_interval(), 300)
        server._do_collect()
        self.assertEqual(server._next_interval(), 600)
        server._do_collect()
        self.assertEqual(server._next_interval(), 1200)

    def test_backoff_is_capped(self):
        server, _, _, _, _ = _make_server(
            collector=_StubCollector(error_bridge("cli_boot_timeout")),
            interval=300, backoff_max=900,
        )
        for _ in range(10):
            server._do_collect()
        self.assertEqual(server._next_interval(), 900)

    def test_success_resets_backoff(self):
        server, _, _, _, _ = _make_server(
            collector=_StubCollector(error_bridge("cli_boot_timeout")),
            interval=300, backoff_max=3600,
        )
        server._do_collect()
        server._do_collect()
        server.collector.result = _ok_bridge()
        server._do_collect()
        self.assertEqual(server._next_interval(), 300)


class TestEscalation(unittest.TestCase):
    """A sustained outage must be loud exactly once, not silent forever."""

    def test_logs_error_once_after_threshold(self):
        server, _, _, _, _ = _make_server(
            collector=_StubCollector(error_bridge("cli_not_authenticated")),
            escalate_after=3,
        )
        with self.assertLogs("tmux_status_server.server", level="ERROR") as cm:
            for _ in range(5):
                server._do_collect()
        self.assertEqual(len(cm.records), 1)
        self.assertIn("cli_not_authenticated", cm.output[0])

    def test_success_rearms_escalation(self):
        server, _, _, _, _ = _make_server(
            collector=_StubCollector(error_bridge("cli_boot_timeout")),
            escalate_after=2,
        )
        logger = logging.getLogger("tmux_status_server.server")
        with mock.patch.object(logger, "error") as err:
            server._do_collect()
            server._do_collect()
            self.assertEqual(err.call_count, 1)
            server.collector.result = _ok_bridge()
            server._do_collect()
            server.collector.result = error_bridge("cli_boot_timeout")
            server._do_collect()
            server._do_collect()
            self.assertEqual(err.call_count, 2)


if __name__ == "__main__":
    unittest.main()
