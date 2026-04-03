"""Tests for deployment files — systemd unit, launchd plist, and Dockerfile."""

import os
import sys
import unittest
import xml.etree.ElementTree as ET

# Add server directory to path so we can import the module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Root of the server/ directory
SERVER_DIR = os.path.join(os.path.dirname(__file__), "..")
DEPLOY_DIR = os.path.join(SERVER_DIR, "deploy")


class TestSystemdServiceExists(unittest.TestCase):
    """Test that the systemd service file exists."""

    def test_service_file_exists(self):
        """tmux-status-server.service exists in deploy/."""
        path = os.path.join(DEPLOY_DIR, "tmux-status-server.service")
        self.assertTrue(os.path.isfile(path))


class TestSystemdServiceUnit(unittest.TestCase):
    """Test systemd unit [Unit] section."""

    def setUp(self):
        path = os.path.join(DEPLOY_DIR, "tmux-status-server.service")
        with open(path) as f:
            self.content = f.read()

    def test_has_unit_section(self):
        """Service file has a [Unit] section."""
        self.assertIn("[Unit]", self.content)

    def test_description(self):
        """Unit has Description=tmux-status quota server."""
        self.assertIn("Description=tmux-status quota server", self.content)

    def test_after_network(self):
        """Unit has After=network.target."""
        self.assertIn("After=network.target", self.content)


class TestSystemdServiceService(unittest.TestCase):
    """Test systemd unit [Service] section."""

    def setUp(self):
        path = os.path.join(DEPLOY_DIR, "tmux-status-server.service")
        with open(path) as f:
            self.content = f.read()

    def test_has_service_section(self):
        """Service file has a [Service] section."""
        self.assertIn("[Service]", self.content)

    def test_exec_start(self):
        """ExecStart uses %h/.local/bin/tmux-status-server."""
        self.assertIn("ExecStart=%h/.local/bin/tmux-status-server", self.content)

    def test_restart_on_failure(self):
        """Restart=on-failure is set."""
        self.assertIn("Restart=on-failure", self.content)

    def test_restart_sec(self):
        """RestartSec=10 is set."""
        self.assertIn("RestartSec=10", self.content)


class TestSystemdServiceInstall(unittest.TestCase):
    """Test systemd unit [Install] section."""

    def setUp(self):
        path = os.path.join(DEPLOY_DIR, "tmux-status-server.service")
        with open(path) as f:
            self.content = f.read()

    def test_has_install_section(self):
        """Service file has an [Install] section."""
        self.assertIn("[Install]", self.content)

    def test_wanted_by_default(self):
        """WantedBy=default.target is set."""
        self.assertIn("WantedBy=default.target", self.content)


class TestSystemdServiceSectionOrder(unittest.TestCase):
    """Test systemd unit section ordering."""

    def setUp(self):
        path = os.path.join(DEPLOY_DIR, "tmux-status-server.service")
        with open(path) as f:
            self.content = f.read()

    def test_section_order(self):
        """Sections appear in correct order: Unit, Service, Install."""
        unit_pos = self.content.index("[Unit]")
        service_pos = self.content.index("[Service]")
        install_pos = self.content.index("[Install]")
        self.assertLess(unit_pos, service_pos)
        self.assertLess(service_pos, install_pos)


class TestLaunchdPlistExists(unittest.TestCase):
    """Test that the launchd plist file exists."""

    def test_plist_file_exists(self):
        """io.mikey.tmux-status-server.plist exists in deploy/."""
        path = os.path.join(DEPLOY_DIR, "io.mikey.tmux-status-server.plist")
        self.assertTrue(os.path.isfile(path))


class TestLaunchdPlistXml(unittest.TestCase):
    """Test that the launchd plist is valid XML."""

    def setUp(self):
        self.path = os.path.join(DEPLOY_DIR, "io.mikey.tmux-status-server.plist")
        with open(self.path) as f:
            self.content = f.read()

    def test_valid_xml(self):
        """Plist parses as valid XML."""
        # Should not raise
        ET.fromstring(self.content)

    def test_xml_declaration(self):
        """Plist has XML declaration."""
        self.assertTrue(self.content.startswith("<?xml"))

    def test_doctype(self):
        """Plist has Apple plist DOCTYPE."""
        self.assertIn("<!DOCTYPE plist", self.content)

    def test_plist_version(self):
        """Plist has version 1.0."""
        self.assertIn('plist version="1.0"', self.content)


class TestLaunchdPlistLabel(unittest.TestCase):
    """Test launchd plist Label key."""

    def setUp(self):
        path = os.path.join(DEPLOY_DIR, "io.mikey.tmux-status-server.plist")
        with open(path) as f:
            self.content = f.read()

    def test_label_value(self):
        """Label is io.mikey.tmux-status-server."""
        self.assertIn("<string>io.mikey.tmux-status-server</string>", self.content)

    def test_label_key_present(self):
        """Label key is present."""
        self.assertIn("<key>Label</key>", self.content)


class TestLaunchdPlistProgram(unittest.TestCase):
    """Test launchd plist ProgramArguments."""

    def setUp(self):
        path = os.path.join(DEPLOY_DIR, "io.mikey.tmux-status-server.plist")
        with open(path) as f:
            self.content = f.read()

    def test_program_arguments_key(self):
        """ProgramArguments key is present."""
        self.assertIn("<key>ProgramArguments</key>", self.content)

    def test_program_path(self):
        """ProgramArguments contains the correct binary path."""
        self.assertIn("<string>~/.local/bin/tmux-status-server</string>", self.content)


class TestLaunchdPlistBehavior(unittest.TestCase):
    """Test launchd plist RunAtLoad and KeepAlive."""

    def setUp(self):
        path = os.path.join(DEPLOY_DIR, "io.mikey.tmux-status-server.plist")
        with open(path) as f:
            self.content = f.read()

    def test_run_at_load_key(self):
        """RunAtLoad key is present."""
        self.assertIn("<key>RunAtLoad</key>", self.content)

    def test_run_at_load_true(self):
        """RunAtLoad is followed by <true/>."""
        # Check that RunAtLoad key is followed by true
        idx = self.content.index("<key>RunAtLoad</key>")
        after = self.content[idx:]
        # The <true/> should appear before any other <key>
        true_pos = after.index("<true/>")
        # Check there's no other key between RunAtLoad and true
        next_key_search = after[len("<key>RunAtLoad</key>"):true_pos]
        self.assertNotIn("<key>", next_key_search)

    def test_keep_alive_key(self):
        """KeepAlive key is present."""
        self.assertIn("<key>KeepAlive</key>", self.content)

    def test_keep_alive_true(self):
        """KeepAlive is followed by <true/>."""
        idx = self.content.index("<key>KeepAlive</key>")
        after = self.content[idx:]
        true_pos = after.index("<true/>")
        next_key_search = after[len("<key>KeepAlive</key>"):true_pos]
        self.assertNotIn("<key>", next_key_search)


class TestDockerfileExists(unittest.TestCase):
    """Test that the Dockerfile exists."""

    def test_dockerfile_exists(self):
        """Dockerfile exists in server/."""
        path = os.path.join(SERVER_DIR, "Dockerfile")
        self.assertTrue(os.path.isfile(path))


class TestDockerfileBase(unittest.TestCase):
    """Test Dockerfile base image."""

    def setUp(self):
        path = os.path.join(SERVER_DIR, "Dockerfile")
        with open(path) as f:
            self.content = f.read()
        self.lines = [line.strip() for line in self.content.splitlines() if line.strip()]

    def test_from_python_slim(self):
        """Dockerfile uses FROM python:3.12-slim."""
        self.assertIn("FROM python:3.12-slim", self.content)

    def test_from_is_first_instruction(self):
        """FROM is the first instruction in the Dockerfile."""
        self.assertTrue(self.lines[0].startswith("FROM python:3.12-slim"))


class TestDockerfileInstall(unittest.TestCase):
    """Test Dockerfile package installation."""

    def setUp(self):
        path = os.path.join(SERVER_DIR, "Dockerfile")
        with open(path) as f:
            self.content = f.read()

    def test_pip_install(self):
        """Dockerfile installs package via pip install ."""
        self.assertIn("pip install", self.content)
        self.assertIn("pip install", self.content)
        # Check for 'pip install .' (with or without flags)
        found = False
        for line in self.content.splitlines():
            stripped = line.strip()
            if "pip install" in stripped and stripped.endswith("."):
                found = True
                break
        self.assertTrue(found, "Dockerfile must contain 'pip install .' (install from current directory)")

    def test_copies_pyproject(self):
        """Dockerfile copies pyproject.toml."""
        self.assertIn("pyproject.toml", self.content)

    def test_copies_package(self):
        """Dockerfile copies the tmux_status_server package directory."""
        self.assertIn("tmux_status_server", self.content)


class TestDockerfileExpose(unittest.TestCase):
    """Test Dockerfile port exposure."""

    def setUp(self):
        path = os.path.join(SERVER_DIR, "Dockerfile")
        with open(path) as f:
            self.content = f.read()

    def test_exposes_7850(self):
        """Dockerfile exposes port 7850."""
        self.assertIn("EXPOSE 7850", self.content)


class TestDockerfileEntrypoint(unittest.TestCase):
    """Test Dockerfile CMD/ENTRYPOINT."""

    def setUp(self):
        path = os.path.join(SERVER_DIR, "Dockerfile")
        with open(path) as f:
            self.content = f.read()

    def test_entrypoint_or_cmd(self):
        """Dockerfile has ENTRYPOINT or CMD set to tmux-status-server."""
        has_entrypoint = "ENTRYPOINT" in self.content and "tmux-status-server" in self.content
        has_cmd = "CMD" in self.content and "tmux-status-server" in self.content
        self.assertTrue(
            has_entrypoint or has_cmd,
            "Dockerfile must have ENTRYPOINT or CMD set to tmux-status-server",
        )

    def test_entrypoint_value(self):
        """ENTRYPOINT contains tmux-status-server."""
        # Find lines with ENTRYPOINT
        for line in self.content.splitlines():
            stripped = line.strip()
            if stripped.startswith("ENTRYPOINT"):
                self.assertIn("tmux-status-server", stripped)
                return
        # If no ENTRYPOINT, check CMD
        for line in self.content.splitlines():
            stripped = line.strip()
            if stripped.startswith("CMD"):
                self.assertIn("tmux-status-server", stripped)
                return
        self.fail("No ENTRYPOINT or CMD found in Dockerfile")


class TestDockerfileWorkdir(unittest.TestCase):
    """Test Dockerfile sets a WORKDIR."""

    def setUp(self):
        path = os.path.join(SERVER_DIR, "Dockerfile")
        with open(path) as f:
            self.content = f.read()

    def test_has_workdir(self):
        """Dockerfile sets a WORKDIR."""
        self.assertIn("WORKDIR", self.content)


if __name__ == "__main__":
    unittest.main()
