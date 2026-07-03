"""Tests for the idle-client prune scheduler deploy files.

The prune scheduler is the periodic backstop for the client-attached hook in
overlay/status.conf: a launchd StartInterval agent (macOS) and a systemd timer
(Linux) that run `tmux-status-prune-clients --reap-transport 7200`. These tests
lock the deploy files' contract and guard against install/uninstall drift (the
files existing but never wired in, or wired in but later removed).
"""

import os
import plistlib
import unittest
import xml.etree.ElementTree as ET

DEPLOY_DIR = os.path.join(os.path.dirname(__file__), "..", "deploy")
REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
PLIST = os.path.join(DEPLOY_DIR, "io.mikey.tmux-status-prune.plist")
SERVICE = os.path.join(DEPLOY_DIR, "tmux-status-prune.service")
TIMER = os.path.join(DEPLOY_DIR, "tmux-status-prune.timer")


class TestPruneLaunchdPlist(unittest.TestCase):
    def setUp(self):
        with open(PLIST) as f:
            self.text = f.read()
        with open(PLIST, "rb") as f:
            self.pl = plistlib.load(f)

    def test_exists(self):
        self.assertTrue(os.path.isfile(PLIST))

    def test_valid_xml(self):
        ET.fromstring(self.text)  # should not raise

    def test_label(self):
        self.assertEqual(self.pl["Label"], "io.mikey.tmux-status-prune")

    def test_program_is_prune_client(self):
        # First arg is the ~ path install.sh rewrites to an absolute path.
        self.assertEqual(
            self.pl["ProgramArguments"][0], "~/.local/bin/tmux-status-prune-clients"
        )

    def test_reaps_transport(self):
        self.assertIn("--reap-transport", self.pl["ProgramArguments"])

    def test_idle_threshold_arg(self):
        # A bare numeric arg (idle seconds) must be present so the agent prunes
        # more aggressively than the tool's 6h default.
        self.assertTrue(
            any(a.isdigit() for a in self.pl["ProgramArguments"][1:]),
            "expected an idle-seconds argument in ProgramArguments",
        )

    def test_periodic(self):
        self.assertIsInstance(self.pl["StartInterval"], int)
        self.assertGreater(self.pl["StartInterval"], 0)

    def test_not_run_at_load(self):
        # Don't prune the instant the agent loads (e.g. mid-install) — wait for
        # the first interval so a just-attached client is never caught.
        self.assertIs(self.pl.get("RunAtLoad", False), False)


class TestPruneSystemdUnits(unittest.TestCase):
    def test_service_exists(self):
        self.assertTrue(os.path.isfile(SERVICE))

    def test_service_is_oneshot(self):
        with open(SERVICE) as f:
            content = f.read()
        self.assertIn("Type=oneshot", content)

    def test_service_reaps_transport(self):
        with open(SERVICE) as f:
            content = f.read()
        self.assertIn(
            "ExecStart=%h/.local/bin/tmux-status-prune-clients --reap-transport", content
        )

    def test_timer_exists(self):
        self.assertTrue(os.path.isfile(TIMER))

    def test_timer_is_periodic(self):
        with open(TIMER) as f:
            content = f.read()
        self.assertIn("[Timer]", content)
        self.assertIn("OnUnitActiveSec=", content)

    def test_timer_install_target(self):
        with open(TIMER) as f:
            content = f.read()
        self.assertIn("WantedBy=timers.target", content)


class TestPruneInstallWiring(unittest.TestCase):
    """Guard against deploy files that exist but are never (un)installed."""

    def setUp(self):
        with open(os.path.join(REPO_ROOT, "install.sh")) as f:
            self.install = f.read()
        with open(os.path.join(REPO_ROOT, "uninstall.sh")) as f:
            self.uninstall = f.read()

    def test_install_references_plist(self):
        self.assertIn("io.mikey.tmux-status-prune.plist", self.install)

    def test_install_references_systemd_units(self):
        self.assertIn("tmux-status-prune.timer", self.install)
        self.assertIn("tmux-status-prune.service", self.install)

    def test_install_enables_timer(self):
        self.assertIn("enable --now tmux-status-prune.timer", self.install)

    def test_uninstall_removes_plist(self):
        self.assertIn("io.mikey.tmux-status-prune", self.uninstall)

    def test_uninstall_removes_timer(self):
        self.assertIn("tmux-status-prune.timer", self.uninstall)


if __name__ == "__main__":
    unittest.main()
