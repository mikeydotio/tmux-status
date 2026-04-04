"""Tests for tmux_status_server.config module."""

import logging
import os
import sys
import unittest

# Add server directory to path so we can import the module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tmux_status_server.config import parse_args, warn_if_exposed


class TestParseArgs(unittest.TestCase):
    """Test CLI argument parsing."""

    def test_defaults(self):
        """All defaults are correct when no arguments supplied."""
        args = parse_args([])
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 7850)
        self.assertEqual(args.interval, 300)
        self.assertEqual(args.log_level, "INFO")
        self.assertIsNone(args.api_key_file)

    def test_key_file_default_with_tilde_expansion(self):
        """--key-file default expands ~ to the home directory."""
        args = parse_args([])
        home = os.path.expanduser("~")
        expected = os.path.join(home, ".config", "tmux-status", "claude-usage-key.json")
        self.assertEqual(args.key_file, expected)
        self.assertNotIn("~", args.key_file)

    def test_custom_host(self):
        """--host overrides the default."""
        args = parse_args(["--host", "0.0.0.0"])
        self.assertEqual(args.host, "0.0.0.0")

    def test_custom_port(self):
        """--port overrides the default."""
        args = parse_args(["--port", "9000"])
        self.assertEqual(args.port, 9000)

    def test_port_is_int(self):
        """--port is parsed as an integer."""
        args = parse_args(["--port", "8080"])
        self.assertIsInstance(args.port, int)

    def test_custom_key_file(self):
        """--key-file overrides the default."""
        args = parse_args(["--key-file", "/tmp/my-key.json"])
        self.assertEqual(args.key_file, "/tmp/my-key.json")

    def test_key_file_tilde_expansion(self):
        """--key-file expands ~ in user-provided paths."""
        args = parse_args(["--key-file", "~/my-key.json"])
        home = os.path.expanduser("~")
        self.assertEqual(args.key_file, os.path.join(home, "my-key.json"))

    def test_api_key_file_optional(self):
        """--api-key-file defaults to None."""
        args = parse_args([])
        self.assertIsNone(args.api_key_file)

    def test_api_key_file_set(self):
        """--api-key-file stores the provided path."""
        args = parse_args(["--api-key-file", "/tmp/api.key"])
        self.assertEqual(args.api_key_file, "/tmp/api.key")

    def test_api_key_file_tilde_expansion(self):
        """--api-key-file expands ~ in the path."""
        args = parse_args(["--api-key-file", "~/api.key"])
        home = os.path.expanduser("~")
        self.assertEqual(args.api_key_file, os.path.join(home, "api.key"))

    def test_custom_interval(self):
        """--interval overrides the default."""
        args = parse_args(["--interval", "60"])
        self.assertEqual(args.interval, 60)

    def test_interval_is_int(self):
        """--interval is parsed as an integer."""
        args = parse_args(["--interval", "120"])
        self.assertIsInstance(args.interval, int)

    def test_custom_log_level(self):
        """--log-level overrides the default."""
        args = parse_args(["--log-level", "DEBUG"])
        self.assertEqual(args.log_level, "DEBUG")

    def test_log_level_invalid_rejected(self):
        """Invalid --log-level values are rejected."""
        with self.assertRaises(SystemExit):
            parse_args(["--log-level", "TRACE"])

    def test_all_args_combined(self):
        """All arguments can be set simultaneously."""
        args = parse_args([
            "--host", "0.0.0.0",
            "--port", "9999",
            "--key-file", "/etc/key.json",
            "--api-key-file", "/etc/api.key",
            "--interval", "60",
            "--log-level", "DEBUG",
        ])
        self.assertEqual(args.host, "0.0.0.0")
        self.assertEqual(args.port, 9999)
        self.assertEqual(args.key_file, "/etc/key.json")
        self.assertEqual(args.api_key_file, "/etc/api.key")
        self.assertEqual(args.interval, 60)
        self.assertEqual(args.log_level, "DEBUG")

    def test_argv_none_uses_sys_argv(self):
        """parse_args(None) uses sys.argv (argparse default behavior)."""
        original = sys.argv
        try:
            sys.argv = ["tmux-status-server", "--port", "1234"]
            args = parse_args(None)
            self.assertEqual(args.port, 1234)
        finally:
            sys.argv = original


class TestWarnIfExposed(unittest.TestCase):
    """Test the non-localhost warning function."""

    def test_no_warning_on_localhost(self):
        """No warning logged when host is 127.0.0.1."""
        args = parse_args([])
        with self.assertLogs(level="WARNING") as cm:
            # Log something to avoid assertLogs error when no logs emitted
            logging.getLogger("test").warning("sentinel")
            warn_if_exposed(args)
        # Only our sentinel should be present
        self.assertEqual(len(cm.output), 1)
        self.assertIn("sentinel", cm.output[0])

    def test_warning_on_non_localhost_without_auth(self):
        """WARNING logged when host is not 127.0.0.1 and api_key_file is None."""
        args = parse_args(["--host", "0.0.0.0"])
        with self.assertLogs(level="WARNING") as cm:
            warn_if_exposed(args)
        # Should contain our specific warning
        warnings = [msg for msg in cm.output if "NO authentication" in msg]
        self.assertEqual(len(warnings), 1)
        self.assertIn("0.0.0.0:7850", warnings[0])
        self.assertIn("NO authentication", warnings[0])

    def test_no_warning_on_non_localhost_with_auth(self):
        """No warning when host is non-localhost but api_key_file is set."""
        args = parse_args(["--host", "0.0.0.0", "--api-key-file", "/tmp/api.key"])
        with self.assertLogs(level="WARNING") as cm:
            logging.getLogger("test").warning("sentinel")
            warn_if_exposed(args)
        self.assertEqual(len(cm.output), 1)
        self.assertIn("sentinel", cm.output[0])

    def test_warning_includes_custom_port(self):
        """Warning message includes the configured port."""
        args = parse_args(["--host", "10.0.0.1", "--port", "9000"])
        with self.assertLogs(level="WARNING") as cm:
            warn_if_exposed(args)
        warnings = [msg for msg in cm.output if "NO authentication" in msg]
        self.assertEqual(len(warnings), 1)
        self.assertIn("10.0.0.1:9000", warnings[0])

    def test_warning_message_format(self):
        """Warning message matches the design specification exactly."""
        args = parse_args(["--host", "0.0.0.0"])
        with self.assertLogs(level="WARNING") as cm:
            warn_if_exposed(args)
        # The design spec says: "WARNING: Listening on 0.0.0.0:7850 with NO authentication."
        # Python logging prepends the level, so we check the message content
        warnings = [msg for msg in cm.output if "NO authentication" in msg]
        self.assertEqual(len(warnings), 1)
        self.assertIn("Listening on 0.0.0.0:7850 with NO authentication.", warnings[0])


class TestStdlibOnly(unittest.TestCase):
    """Verify the module uses only standard library imports."""

    def test_no_external_imports(self):
        """config.py imports only stdlib modules."""
        import importlib
        import ast

        config_path = os.path.join(
            os.path.dirname(__file__), "..", "tmux_status_server", "config.py"
        )
        with open(config_path) as f:
            tree = ast.parse(f.read())

        stdlib_modules = {"argparse", "logging", "os", "pathlib", "sys"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertIn(
                        alias.name, stdlib_modules,
                        f"Non-stdlib import: {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top_level = node.module.split(".")[0]
                    self.assertIn(
                        top_level, stdlib_modules,
                        f"Non-stdlib import: {node.module}"
                    )


# ---------------------------------------------------------------------------
# Validate: Additional config edge cases
# ---------------------------------------------------------------------------

class TestConfigDefaults(unittest.TestCase):
    """Verify default values match the design specification."""

    def test_default_host_is_localhost(self):
        """Default host is 127.0.0.1 (R19 — secure default)."""
        args = parse_args([])
        self.assertEqual(args.host, "127.0.0.1")

    def test_default_port_is_7850(self):
        """Default port is 7850 (design spec)."""
        args = parse_args([])
        self.assertEqual(args.port, 7850)

    def test_default_interval_is_300(self):
        """Default interval is 300 seconds (5 minutes)."""
        args = parse_args([])
        self.assertEqual(args.interval, 300)

    def test_default_log_level_is_info(self):
        """Default log level is INFO."""
        args = parse_args([])
        self.assertEqual(args.log_level, "INFO")


class TestWarnIfExposedLocalhostVariants(unittest.TestCase):
    """Test warn_if_exposed with localhost variants."""

    def test_no_warning_on_ipv4_localhost(self):
        """127.0.0.1 does not trigger a warning."""
        args = parse_args(["--host", "127.0.0.1"])
        with self.assertLogs(level="WARNING") as cm:
            logging.getLogger("test").warning("sentinel")
            warn_if_exposed(args)
        self.assertEqual(len(cm.output), 1)
        self.assertIn("sentinel", cm.output[0])

    def test_no_warning_on_localhost_name(self):
        """localhost does not trigger a warning."""
        args = parse_args(["--host", "localhost"])
        with self.assertLogs(level="WARNING") as cm:
            logging.getLogger("test").warning("sentinel")
            warn_if_exposed(args)
        self.assertEqual(len(cm.output), 1)
        self.assertIn("sentinel", cm.output[0])

    def test_no_warning_on_ipv6_loopback(self):
        """::1 does not trigger a warning."""
        args = parse_args(["--host", "::1"])
        with self.assertLogs(level="WARNING") as cm:
            logging.getLogger("test").warning("sentinel")
            warn_if_exposed(args)
        self.assertEqual(len(cm.output), 1)
        self.assertIn("sentinel", cm.output[0])

    def test_warning_on_all_interfaces(self):
        """0.0.0.0 triggers a warning when no auth configured."""
        args = parse_args(["--host", "0.0.0.0"])
        with self.assertLogs(level="WARNING") as cm:
            warn_if_exposed(args)
        warnings = [msg for msg in cm.output if "NO authentication" in msg]
        self.assertEqual(len(warnings), 1)

    def test_warning_on_private_ip(self):
        """192.168.1.1 triggers a warning when no auth configured."""
        args = parse_args(["--host", "192.168.1.1"])
        with self.assertLogs(level="WARNING") as cm:
            warn_if_exposed(args)
        warnings = [msg for msg in cm.output if "NO authentication" in msg]
        self.assertEqual(len(warnings), 1)
        self.assertIn("192.168.1.1", warnings[0])


if __name__ == "__main__":
    unittest.main()
