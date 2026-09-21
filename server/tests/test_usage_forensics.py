"""Tests for usage-collection failure forensics (TS-56).

The 2026-09-08 outage could not be diagnosed after the fact because the screen
the collector timed out on was never persisted — every one of 35 failures
logged the same six false booleans. These tests pin the two fixes: classifying
an unrecognised screen apart from a dead CLI, and writing the screen to disk.

See ``docs/spec/quota-resilience.md``.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tmux_status_server import cli_usage  # noqa: E402
from tmux_status_server.cli_usage import HeadlessClaudeSession, UsageError  # noqa: E402


READY = "plan mode on (shift+tab to cycle)"


def _session(screen, failure_path):
    """A session whose pane always shows ``screen``, recording to a temp path."""
    s = HeadlessClaudeSession(boot_timeout=0.01, screen_timeout=0.01)
    s._capture = lambda: screen
    s.failure_screen_path = failure_path
    return s


class TestUnknownScreenClassification(unittest.TestCase):
    """"Booted into something I don't recognise" is not "the CLI is dead"."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "usage-failure.txt")

    def tearDown(self):
        self.tmp.cleanup()

    def test_blank_screen_is_still_a_boot_timeout(self):
        s = _session("", self.path)
        with self.assertRaises(UsageError) as ctx:
            s._wait_for(s.is_ready, 0.01, "cli_boot_timeout")
        self.assertEqual(ctx.exception.code, "cli_boot_timeout")

    def test_unrecognised_screen_is_classified_separately(self):
        s = _session("Something entirely new the CLI now shows\nPress enter", self.path)
        with self.assertRaises(UsageError) as ctx:
            s._wait_for(s.is_ready, 0.01, "cli_boot_timeout")
        self.assertEqual(ctx.exception.code, "cli_unknown_screen")

    def test_known_blocking_screen_keeps_its_own_code(self):
        s = _session("Select login method\nAnthropic Console account", self.path)
        with self.assertRaises(UsageError) as ctx:
            s._wait_for(s.is_ready, 0.01, "cli_boot_timeout")
        self.assertEqual(ctx.exception.code, "cli_boot_timeout")


class TestFailureScreenPersistence(unittest.TestCase):
    """The screen that caused the failure must survive the failure."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "usage-failure.txt")

    def tearDown(self):
        self.tmp.cleanup()

    def test_screen_written_on_timeout(self):
        s = _session("A brand new interstitial\nContinue?", self.path)
        with self.assertRaises(UsageError):
            s._wait_for(s.is_ready, 0.01, "cli_boot_timeout")
        with open(self.path) as f:
            written = f.read()
        self.assertIn("A brand new interstitial", written)
        self.assertIn("cli_unknown_screen", written)

    def test_overwrites_rather_than_growing(self):
        s = _session("first screen", self.path)
        with self.assertRaises(UsageError):
            s._wait_for(s.is_ready, 0.01, "cli_boot_timeout")
        s._capture = lambda: "second screen"
        with self.assertRaises(UsageError):
            s._wait_for(s.is_ready, 0.01, "cli_boot_timeout")
        with open(self.path) as f:
            written = f.read()
        self.assertIn("second screen", written)
        self.assertNotIn("first screen", written)

    def test_write_failure_never_masks_the_original_error(self):
        s = _session("unknown", os.path.join(self.tmp.name, "no", "such", "dir", "f"))
        with self.assertRaises(UsageError) as ctx:
            s._wait_for(s.is_ready, 0.01, "cli_boot_timeout")
        self.assertEqual(ctx.exception.code, "cli_unknown_screen")


class TestRedaction(unittest.TestCase):
    """A persisted screen must not become a place credentials land."""

    def test_token_shaped_runs_are_redacted(self):
        token = "sk-ant-oat01-" + "A1b2C3d4" * 8
        out = cli_usage.redact_screen(f"env CLAUDE_CODE_OAUTH_TOKEN={token} set")
        self.assertNotIn(token, out)
        self.assertIn("<redacted>", out)

    def test_ordinary_screen_text_survives(self):
        screen = "Current week (all models)\n61% used\nResets Sep 17 at 9am"
        self.assertEqual(cli_usage.redact_screen(screen), screen)


class TestDefaultPath(unittest.TestCase):
    """The default location is discoverable next to the other cache files."""

    def test_default_under_tmux_status_cache(self):
        path = cli_usage.default_failure_screen_path()
        self.assertTrue(path.endswith(os.path.join("tmux-status", "usage-failure.txt")))


if __name__ == "__main__":
    unittest.main()
