"""Tests for the render daemon deploy files — launchd plist and systemd unit."""

import os
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

DEPLOY_DIR = os.path.join(os.path.dirname(__file__), "..", "deploy")
PLIST = os.path.join(DEPLOY_DIR, "io.mikey.tmux-status-renderd.plist")
UNIT = os.path.join(DEPLOY_DIR, "tmux-status-renderd.service")


class TestRenderdSystemdUnit(unittest.TestCase):
    def setUp(self):
        with open(UNIT) as f:
            self.content = f.read()

    def test_exists(self):
        self.assertTrue(os.path.isfile(UNIT))

    def test_sections(self):
        self.assertIn("[Unit]", self.content)
        self.assertIn("[Service]", self.content)
        self.assertIn("[Install]", self.content)

    def test_description(self):
        self.assertIn("Description=tmux-status Claude/Codex agent render daemon", self.content)

    def test_exec_start(self):
        self.assertIn("ExecStart=%h/.local/bin/tmux-status-renderd", self.content)

    def test_restart_policy(self):
        self.assertIn("Restart=on-failure", self.content)
        self.assertIn("RestartSec=10", self.content)

    def test_wanted_by(self):
        self.assertIn("WantedBy=default.target", self.content)

    def test_section_order(self):
        self.assertLess(self.content.index("[Unit]"), self.content.index("[Service]"))
        self.assertLess(self.content.index("[Service]"), self.content.index("[Install]"))


class TestRenderdLaunchdPlist(unittest.TestCase):
    def setUp(self):
        with open(PLIST) as f:
            self.content = f.read()

    def test_exists(self):
        self.assertTrue(os.path.isfile(PLIST))

    def test_valid_xml(self):
        ET.fromstring(self.content)  # should not raise

    def test_dual_provider_description(self):
        self.assertIn("Claude Code and Codex agent status render daemon", self.content)

    def test_label(self):
        self.assertIn("<string>io.mikey.tmux-status-renderd</string>", self.content)

    def test_program_path(self):
        self.assertIn("<string>~/.local/bin/tmux-status-renderd</string>", self.content)

    def test_run_at_load_true(self):
        idx = self.content.index("<key>RunAtLoad</key>")
        after = self.content[idx + len("<key>RunAtLoad</key>"):]
        self.assertNotIn("<key>", after[:after.index("<true/>")])

    def test_keep_alive_true(self):
        idx = self.content.index("<key>KeepAlive</key>")
        after = self.content[idx + len("<key>KeepAlive</key>"):]
        self.assertNotIn("<key>", after[:after.index("<true/>")])


class TestRenderdEntryPoint(unittest.TestCase):
    def test_pyproject_declares_renderd(self):
        pyproject = os.path.join(DEPLOY_DIR, "..", "pyproject.toml")
        with open(pyproject) as f:
            content = f.read()
        self.assertIn('tmux-status-renderd = "tmux_status_server.renderd_entry:main"', content)


if __name__ == "__main__":
    unittest.main()
