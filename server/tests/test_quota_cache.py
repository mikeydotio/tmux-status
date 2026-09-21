"""Tests for the render daemon's quota cache and age contract (TS-56).

``_maybe_fetch_quota`` used to validate only that the response parsed as JSON,
then write it over the last-known-good cache — so the first error bridge of an
outage destroyed a six-minute-old correct reading. These tests pin the
replacement: errors land beside the cache, and a reading's status is derived
from its age.

See ``docs/spec/quota-resilience.md``.
"""

import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tmux_status_server import render  # noqa: E402
from tmux_status_server.cli_usage import error_bridge  # noqa: E402

from test_server import _ok_bridge  # noqa: E402


# ── Render daemon: the disk cache is never poisoned ────────────────────────
class TestQuotaCacheRetention(unittest.TestCase):
    """``_maybe_fetch_quota`` must not overwrite good numbers with an error."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = os.path.join(self.tmp.name, "claude-quota.json")

    def tearDown(self):
        self.tmp.cleanup()

    def _fetch(self, payload):
        class _Resp:
            def __init__(self, data):
                self._data = data

            def read(self):
                return json.dumps(self._data).encode()

        with mock.patch.object(render.urllib.request, "urlopen",
                               return_value=_Resp(payload)):
            render._maybe_fetch_quota("http://x", "", 0, self.cache)

    def test_ok_response_writes_cache(self):
        self._fetch(_ok_bridge())
        with open(self.cache) as f:
            self.assertEqual(json.load(f)["five_hour"]["utilization"], 42)

    def test_error_response_does_not_overwrite_good_cache(self):
        self._fetch(_ok_bridge())
        self._fetch(error_bridge("cli_not_authenticated"))
        with open(self.cache) as f:
            kept = json.load(f)
        self.assertEqual(kept["five_hour"]["utilization"], 42)

    def test_error_response_recorded_alongside(self):
        self._fetch(_ok_bridge())
        self._fetch(error_bridge("cli_not_authenticated"))
        with open(render.quota_error_path(self.cache)) as f:
            self.assertEqual(json.load(f)["error"], "cli_not_authenticated")

    def test_stale_response_keeps_numbers(self):
        bridge = dict(_ok_bridge(), status="stale", age_seconds=900,
                      error="cli_not_authenticated")
        self._fetch(bridge)
        with open(self.cache) as f:
            self.assertEqual(json.load(f)["five_hour"]["utilization"], 42)


class TestComputeQuotaAge(unittest.TestCase):
    """The rendered vars must carry how old the numbers are."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = os.path.join(self.tmp.name, "claude-quota.json")
        self.settings = {
            "quota_bridge": self.cache,
            "quota_source": "",
            "quota_api_key": "",
            "quota_cache_ttl": 0,
            "quota_max_stale": 300,
            "quota_good_max": 86400,
        }

    def tearDown(self):
        self.tmp.cleanup()

    def _write_bridge(self, **over):
        bridge = _ok_bridge()
        bridge["timestamp"] = int(time.time())
        bridge.update(over)
        with open(self.cache, "w") as f:
            json.dump(bridge, f)

    def test_fresh_bridge_renders_ok(self):
        self._write_bridge()
        out = render.compute_quota_vars(self.settings, os.path.expanduser("~"))
        self.assertEqual(out["quota_status"], "ok")
        self.assertEqual(out["five_hour_pct"], 42)

    def test_stale_bridge_keeps_numbers_and_reports_age(self):
        self._write_bridge(timestamp=int(time.time()) - 900)
        out = render.compute_quota_vars(self.settings, os.path.expanduser("~"))
        self.assertEqual(out["quota_status"], "stale")
        self.assertEqual(out["five_hour_pct"], 42)
        self.assertGreaterEqual(out["quota_age"], 900)

    def test_expired_bridge_renders_x_with_age(self):
        self._write_bridge(timestamp=int(time.time()) - 200000)
        out = render.compute_quota_vars(self.settings, os.path.expanduser("~"))
        self.assertEqual(out["quota_status"], "error")
        self.assertEqual(out["five_hour_pct"], "X")
        self.assertGreaterEqual(out["quota_age"], 200000)

    def test_age_is_human_formatted(self):
        self.assertEqual(render.fmt_age(45), "45s")
        self.assertEqual(render.fmt_age(900), "15m")
        self.assertEqual(render.fmt_age(7200), "2h")
        self.assertEqual(render.fmt_age(345600), "4d")

if __name__ == "__main__":
    unittest.main()
