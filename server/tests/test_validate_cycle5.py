"""Validation pass 5: Tests for fix cycle 5 ESCALATE fixes.

Covers:
- TS-31: tmux-claude-status case pattern includes session_key_expired, no bare expired
- TS-33: tmux-claude-status pidfile reads use sys.argv[1], no string interpolation
- TS-32: Dockerfile USER directive (supplementary to test_deploy.py)
- TS-34: Context hook JS uses atomic writes (tmp + renameSync)
- TS-35: Legacy quota scripts removed from repo and install.sh SCRIPTS array
- TS-37: --interval lower bound validation edge cases (supplementary to test_config.py)
"""

import os
import re
import sys
import unittest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
INSTALL_SH = os.path.join(REPO_ROOT, "install.sh")
CONTEXT_HOOK = os.path.join(SCRIPTS_DIR, "tmux-status-context-hook.js")
CLAUDE_STATUS = os.path.join(SCRIPTS_DIR, "tmux-claude-status")
DOCKERFILE = os.path.join(REPO_ROOT, "server", "Dockerfile")

# Add server directory to path for config import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# TS-31: Status code mismatch fix
# ---------------------------------------------------------------------------

class TestTS31StatusCodeCasePattern(unittest.TestCase):
    """Verify tmux-claude-status case pattern uses session_key_expired not bare expired."""

    def setUp(self):
        with open(CLAUDE_STATUS) as f:
            self.content = f.read()
        self.lines = self.content.splitlines()

    def test_case_pattern_contains_session_key_expired(self):
        """Case pattern for QUOTA_STATUS includes session_key_expired."""
        # Find the case pattern near QUOTA_STATUS
        found = False
        for line in self.lines:
            if "session_key_expired" in line and "QUOTA_COLOR" in line:
                found = True
                break
        self.assertTrue(found,
                        "Case pattern must include session_key_expired for QUOTA_COLOR")

    def test_case_pattern_no_bare_expired_as_standalone(self):
        """Case pattern does not have bare 'expired' as a standalone alternative.

        The word 'expired' may appear as part of 'session_key_expired' or
        'key_expired', but NOT as a standalone '|expired|' or '|expired)' pattern.
        """
        for line in self.lines:
            if "QUOTA_COLOR" in line and "case" not in line.lower():
                # This is the pattern line like:
                # session_key_expired|blocked|error|rate_limited|key_expired)
                alternatives = re.findall(r'(\w+)', line)
                for alt in alternatives:
                    if alt == "expired":
                        self.fail(
                            f"Found bare 'expired' as standalone alternative in case "
                            f"pattern: {line.strip()}"
                        )

    def test_all_expected_error_statuses_present(self):
        """Case pattern includes all design-specified error statuses."""
        expected = {"session_key_expired", "blocked", "error", "rate_limited", "key_expired"}
        found_line = None
        for line in self.lines:
            if "session_key_expired" in line and "QUOTA_COLOR" in line:
                found_line = line
                break
        self.assertIsNotNone(found_line, "Could not find case pattern line")
        for status in expected:
            self.assertIn(status, found_line,
                          f"Missing status '{status}' in case pattern")

    def test_case_pattern_sets_red_color(self):
        """Error statuses set QUOTA_COLOR to colour196 (red)."""
        for line in self.lines:
            if "session_key_expired" in line and "QUOTA_COLOR" in line:
                self.assertIn("colour196", line,
                              "Error statuses should set colour196 (red)")
                return
        self.fail("Could not find session_key_expired case pattern")


# ---------------------------------------------------------------------------
# TS-33: Shell injection fix (sys.argv pidfile)
# ---------------------------------------------------------------------------

class TestTS33SysArgvPidfile(unittest.TestCase):
    """Verify tmux-claude-status passes pidfile via sys.argv, not interpolation."""

    def setUp(self):
        with open(CLAUDE_STATUS) as f:
            self.content = f.read()
        self.lines = self.content.splitlines()

    def test_no_string_interpolation_of_pidfile_in_open(self):
        """No occurrence of open('$pidfile') or open(\"$pidfile\") in the script."""
        # These patterns would indicate shell variable interpolation inside Python
        self.assertNotIn("open('$pidfile')", self.content)
        self.assertNotIn('open("$pidfile")', self.content)

    def test_pid_read_uses_sys_argv(self):
        """The pid extraction line uses sys.argv[1] to receive the pidfile path."""
        pid_lines = [l for l in self.lines if "['pid']" in l and "python3" in l]
        self.assertTrue(len(pid_lines) >= 1,
                        "Expected at least one line reading pid via python3")
        for line in pid_lines:
            self.assertIn("sys.argv[1]", line,
                          f"pid read should use sys.argv[1]: {line.strip()}")

    def test_cwd_read_uses_sys_argv(self):
        """The cwd extraction line uses sys.argv[1] to receive the pidfile path."""
        cwd_lines = [l for l in self.lines if "['cwd']" in l and "python3" in l]
        self.assertTrue(len(cwd_lines) >= 1,
                        "Expected at least one line reading cwd via python3")
        for line in cwd_lines:
            self.assertIn("sys.argv[1]", line,
                          f"cwd read should use sys.argv[1]: {line.strip()}")

    def test_pidfile_passed_as_positional_arg(self):
        """The shell passes \"$pidfile\" as a positional argument to python3."""
        # Look for the pattern: python3 -c "..." "$pidfile"
        pid_lines = [l for l in self.lines
                     if "python3 -c" in l and "pidfile" in l]
        for line in pid_lines:
            # After the closing quote of the python code, "$pidfile" should appear
            self.assertRegex(
                line.strip(),
                r'"\s+"?\$pidfile"?',
                f"pidfile should be passed as positional arg: {line.strip()}"
            )

    def test_script_is_executable(self):
        """tmux-claude-status is executable."""
        self.assertTrue(os.access(CLAUDE_STATUS, os.X_OK),
                        "tmux-claude-status must be executable")


# ---------------------------------------------------------------------------
# TS-32: Dockerfile non-root USER (supplementary)
# ---------------------------------------------------------------------------

class TestTS32DockerfileUserCreation(unittest.TestCase):
    """Verify Dockerfile creates and uses a non-root user."""

    def setUp(self):
        with open(DOCKERFILE) as f:
            self.content = f.read()
        self.lines = self.content.splitlines()

    def test_useradd_instruction_present(self):
        """Dockerfile has a RUN instruction that creates a user via useradd."""
        found = any("useradd" in line for line in self.lines)
        self.assertTrue(found,
                        "Dockerfile should use useradd to create a non-root user")

    def test_user_has_nologin_shell(self):
        """Created user has /usr/sbin/nologin or /sbin/nologin shell."""
        for line in self.lines:
            if "useradd" in line:
                self.assertTrue(
                    "nologin" in line,
                    "System user should have nologin shell for security"
                )
                return
        self.fail("No useradd instruction found")

    def test_user_is_system_user(self):
        """Created user is a system user (useradd -r)."""
        for line in self.lines:
            if "useradd" in line:
                self.assertIn("-r", line,
                              "User should be a system user (useradd -r)")
                return
        self.fail("No useradd instruction found")


# ---------------------------------------------------------------------------
# TS-34: Context hook atomic writes
# ---------------------------------------------------------------------------

class TestTS34ContextHookAtomicWrites(unittest.TestCase):
    """Verify tmux-status-context-hook.js uses atomic write pattern."""

    def setUp(self):
        with open(CONTEXT_HOOK) as f:
            self.content = f.read()

    def test_writes_to_tmp_path_not_final(self):
        """writeFileSync writes to a .tmp path, not the final bridgePath."""
        # Find writeFileSync calls
        write_calls = re.findall(r'fs\.writeFileSync\((\w+)', self.content)
        self.assertTrue(len(write_calls) >= 1,
                        "Expected at least one writeFileSync call")
        for var in write_calls:
            self.assertNotEqual(var, "bridgePath",
                                "writeFileSync must NOT write directly to bridgePath")
            self.assertIn("tmp", var.lower(),
                          f"writeFileSync should write to a tmp variable, got: {var}")

    def test_rename_sync_present(self):
        """fs.renameSync is used to atomically move tmp to final path."""
        self.assertIn("fs.renameSync", self.content,
                       "Must use fs.renameSync for atomic write")

    def test_rename_moves_tmp_to_bridge(self):
        """renameSync moves from tmpPath to bridgePath."""
        rename_match = re.search(r'fs\.renameSync\((\w+),\s*(\w+)\)', self.content)
        self.assertIsNotNone(rename_match, "Expected fs.renameSync(src, dest) call")
        src, dest = rename_match.group(1), rename_match.group(2)
        self.assertIn("tmp", src.lower(),
                      f"renameSync source should be tmp path, got: {src}")
        self.assertIn("bridge", dest.lower(),
                      f"renameSync dest should be bridge path, got: {dest}")

    def test_tmp_path_derived_from_bridge_path(self):
        """tmpPath is constructed from bridgePath + '.tmp'."""
        self.assertRegex(self.content, r"bridgePath\s*\+\s*['\"]\.tmp['\"]",
                         "tmpPath should be bridgePath + '.tmp'")

    def test_no_bare_write_to_bridge_path(self):
        """No writeFileSync(bridgePath, ...) call exists."""
        # More thorough check: look for writeFileSync with bridgePath as first arg
        self.assertNotRegex(
            self.content,
            r'writeFileSync\(bridgePath\s*,',
            "Must not write directly to bridgePath"
        )

    def test_script_is_executable(self):
        """tmux-status-context-hook.js is executable."""
        self.assertTrue(os.access(CONTEXT_HOOK, os.X_OK),
                        "tmux-status-context-hook.js must be executable")


# ---------------------------------------------------------------------------
# TS-35: Legacy quota script removal
# ---------------------------------------------------------------------------

class TestTS35LegacyScriptRemoval(unittest.TestCase):
    """Verify legacy quota scripts are removed from repo and install.sh."""

    def test_quota_fetch_script_does_not_exist(self):
        """scripts/tmux-status-quota-fetch does not exist in the repo."""
        path = os.path.join(SCRIPTS_DIR, "tmux-status-quota-fetch")
        self.assertFalse(os.path.exists(path),
                         "tmux-status-quota-fetch should be deleted")

    def test_quota_poll_script_does_not_exist(self):
        """scripts/tmux-status-quota-poll does not exist in the repo."""
        path = os.path.join(SCRIPTS_DIR, "tmux-status-quota-poll")
        self.assertFalse(os.path.exists(path),
                         "tmux-status-quota-poll should be deleted")

    def test_install_sh_scripts_array_no_quota_fetch(self):
        """install.sh SCRIPTS array does not include tmux-status-quota-fetch."""
        with open(INSTALL_SH) as f:
            content = f.read()
        # Find the SCRIPTS=(...) array
        match = re.search(r'SCRIPTS=\(([^)]+)\)', content)
        self.assertIsNotNone(match, "Could not find SCRIPTS array in install.sh")
        scripts_str = match.group(1)
        self.assertNotIn("tmux-status-quota-fetch", scripts_str,
                         "SCRIPTS array must not include tmux-status-quota-fetch")

    def test_install_sh_scripts_array_no_quota_poll(self):
        """install.sh SCRIPTS array does not include tmux-status-quota-poll."""
        with open(INSTALL_SH) as f:
            content = f.read()
        match = re.search(r'SCRIPTS=\(([^)]+)\)', content)
        self.assertIsNotNone(match)
        scripts_str = match.group(1)
        self.assertNotIn("tmux-status-quota-poll", scripts_str,
                         "SCRIPTS array must not include tmux-status-quota-poll")

    def test_install_sh_scripts_array_has_expected_scripts(self):
        """install.sh SCRIPTS array contains exactly the 5 expected scripts."""
        with open(INSTALL_SH) as f:
            content = f.read()
        match = re.search(r'SCRIPTS=\(([^)]+)\)', content)
        self.assertIsNotNone(match)
        scripts = match.group(1).split()
        expected = {
            "tmux-claude-status",
            "tmux-git-status",
            "tmux-status-apply-config",
            "tmux-status-session",
            "tmux-status-context-hook.js",
        }
        self.assertEqual(set(scripts), expected,
                         f"SCRIPTS array should contain exactly: {expected}")

    def test_all_listed_scripts_exist(self):
        """Every script in the SCRIPTS array exists in the scripts/ directory."""
        with open(INSTALL_SH) as f:
            content = f.read()
        match = re.search(r'SCRIPTS=\(([^)]+)\)', content)
        self.assertIsNotNone(match)
        scripts = match.group(1).split()
        for script in scripts:
            path = os.path.join(SCRIPTS_DIR, script)
            self.assertTrue(os.path.exists(path),
                            f"Script {script} listed in SCRIPTS but not found at {path}")


# ---------------------------------------------------------------------------
# TS-37: Interval lower bound validation (supplementary edge cases)
# ---------------------------------------------------------------------------

class TestTS37IntervalBoundaryEdgeCases(unittest.TestCase):
    """Additional edge cases for --interval validation boundary."""

    def test_interval_negative_value_rejected(self):
        """--interval -1 is rejected (below minimum 30)."""
        from tmux_status_server.config import parse_args
        with self.assertRaises(SystemExit):
            parse_args(["--interval", "-1"])

    def test_interval_negative_large_rejected(self):
        """--interval -100 is rejected."""
        from tmux_status_server.config import parse_args
        with self.assertRaises(SystemExit):
            parse_args(["--interval", "-100"])

    def test_interval_31_accepted(self):
        """--interval 31 is accepted (just above boundary)."""
        from tmux_status_server.config import parse_args
        args = parse_args(["--interval", "31"])
        self.assertEqual(args.interval, 31)

    def test_interval_large_value_accepted(self):
        """--interval 86400 (24 hours) is accepted."""
        from tmux_status_server.config import parse_args
        args = parse_args(["--interval", "86400"])
        self.assertEqual(args.interval, 86400)

    def test_interval_exactly_30_boundary(self):
        """--interval 30 is the minimum accepted value."""
        from tmux_status_server.config import parse_args
        args = parse_args(["--interval", "30"])
        self.assertEqual(args.interval, 30)

    def test_interval_29_is_maximum_rejected(self):
        """--interval 29 is the maximum rejected value."""
        from tmux_status_server.config import parse_args
        with self.assertRaises(SystemExit):
            parse_args(["--interval", "29"])


# ---------------------------------------------------------------------------
# Cross-cutting: Syntax validation
# ---------------------------------------------------------------------------

class TestScriptSyntaxValidation(unittest.TestCase):
    """Verify all scripts pass syntax checking."""

    def test_tmux_claude_status_is_valid_bash(self):
        """tmux-claude-status passes bash -n syntax check."""
        import subprocess
        result = subprocess.run(
            ["bash", "-n", CLAUDE_STATUS],
            capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0,
                         f"bash -n failed: {result.stderr}")

    def test_install_sh_is_valid_bash(self):
        """install.sh passes bash -n syntax check."""
        import subprocess
        result = subprocess.run(
            ["bash", "-n", INSTALL_SH],
            capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0,
                         f"bash -n failed: {result.stderr}")

    def test_context_hook_is_valid_js(self):
        """tmux-status-context-hook.js passes node -c syntax check."""
        import subprocess
        result = subprocess.run(
            ["node", "-c", CONTEXT_HOOK],
            capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0,
                         f"node -c failed: {result.stderr}")

    def test_all_bash_scripts_valid_syntax(self):
        """All bash scripts in scripts/ pass bash -n."""
        import subprocess
        bash_scripts = [
            "tmux-claude-status",
            "tmux-git-status",
            "tmux-status-apply-config",
            "tmux-status-session",
        ]
        for script in bash_scripts:
            path = os.path.join(SCRIPTS_DIR, script)
            if os.path.exists(path):
                result = subprocess.run(
                    ["bash", "-n", path],
                    capture_output=True, text=True
                )
                self.assertEqual(result.returncode, 0,
                                 f"bash -n failed for {script}: {result.stderr}")


# ---------------------------------------------------------------------------
# Cross-cutting: Renderer error status display consistency
# ---------------------------------------------------------------------------

class TestRendererQuotaStatusConsistency(unittest.TestCase):
    """Verify the renderer's case pattern is consistent with server error statuses."""

    def setUp(self):
        with open(CLAUDE_STATUS) as f:
            self.content = f.read()

    def test_renderer_case_pattern_matches_design_spec(self):
        """Renderer case pattern includes all statuses from DESIGN.md error table.

        The DESIGN.md error table lists: expired (now session_key_expired),
        blocked, rate_limited, no_key, upstream_error, starting.
        The renderer groups error display statuses that should show red.
        """
        # The case pattern should handle error-class statuses
        error_statuses_requiring_red = {
            "session_key_expired",
            "blocked",
            "error",
            "rate_limited",
            "key_expired",
        }
        for line in self.content.splitlines():
            if "session_key_expired" in line and "QUOTA_COLOR" in line:
                for status in error_statuses_requiring_red:
                    self.assertIn(status, line,
                                  f"Missing {status} in renderer error case pattern")
                return
        self.fail("Could not find error status case pattern in renderer")

    def test_no_key_and_none_handled_separately(self):
        """no_key and none statuses are handled by the omit-quota-section branch."""
        # These statuses cause the quota section to be hidden entirely
        # rather than displayed in red
        for line in self.content.splitlines():
            if "no_key" in line and "none" in line:
                self.assertIn("QUOTA_STATUS", line,
                              "no_key/none check should reference QUOTA_STATUS")
                return
        self.fail("Could not find no_key/none handling in renderer")


if __name__ == "__main__":
    unittest.main()
