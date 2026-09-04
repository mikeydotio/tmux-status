"""Regression tests for TS-52's console-entry signal-safety invariant."""

import ast
import os
import subprocess
import sys
import unittest

SERVER_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PYPROJECT = os.path.join(SERVER_ROOT, "pyproject.toml")


def _console_script_modules():
    """Return ``{command: module}`` from pyproject's project.scripts table."""
    modules = {}
    in_scripts = False
    with open(PYPROJECT) as pyproject:
        for raw_line in pyproject:
            line = raw_line.strip()
            if line == "[project.scripts]":
                in_scripts = True
                continue
            if in_scripts and line.startswith("["):
                break
            if not in_scripts or not line or line.startswith("#"):
                continue
            command, separator, target = line.partition("=")
            if not separator:
                continue
            module = target.strip().strip('"').partition(":")[0]
            modules[command.strip()] = module
    return modules


def _is_package_import(node):
    """Return whether a top-level AST node imports tmux_status_server."""
    if isinstance(node, ast.Import):
        return any(alias.name.startswith("tmux_status_server") for alias in node.names)
    return isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
        "tmux_status_server"
    )


def _is_sigusr1_ignore(node):
    """Return whether a node is ``signal.signal(SIGUSR1, SIG_IGN)``."""
    if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
        return False
    call = node.value
    return (
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "signal"
        and call.func.attr == "signal"
        and len(call.args) >= 2
        and isinstance(call.args[0], ast.Attribute)
        and isinstance(call.args[0].value, ast.Name)
        and call.args[0].value.id == "signal"
        and call.args[0].attr == "SIGUSR1"
        and isinstance(call.args[1], ast.Attribute)
        and isinstance(call.args[1].value, ast.Name)
        and call.args[1].value.id == "signal"
        and call.args[1].attr == "SIG_IGN"
    )


class TestConsoleEntrySignalSafety(unittest.TestCase):
    """Prove every packaged command neutralizes SIGUSR1 before heavy imports."""

    def setUp(self):
        self.scripts = _console_script_modules()
        self.assertGreaterEqual(len(self.scripts), 2, "console-script scan was vacuous")

    def test_every_entry_ignores_sigusr1_before_package_import(self):
        """A package import must never precede the protective disposition."""
        for command, module in self.scripts.items():
            with self.subTest(command=command):
                source_path = os.path.join(SERVER_ROOT, *module.split(".")) + ".py"
                with open(source_path) as source_file:
                    tree = ast.parse(source_file.read(), filename=source_path)
                ignore_lines = [node.lineno for node in tree.body if _is_sigusr1_ignore(node)]
                import_lines = [node.lineno for node in tree.body if _is_package_import(node)]
                self.assertTrue(ignore_lines, f"{module} does not ignore SIGUSR1")
                self.assertTrue(import_lines, f"{module} does not delegate to the package")
                self.assertLess(
                    min(ignore_lines), min(import_lines),
                    f"{module} imports package code before ignoring SIGUSR1",
                )

    def test_every_entry_leaves_sigusr1_ignored_after_import(self):
        """Fresh subprocesses prove each entry's effective disposition."""
        for command, module in self.scripts.items():
            with self.subTest(command=command):
                code = (
                    "import sys, signal; "
                    f"sys.path.insert(0, {SERVER_ROOT!r}); "
                    f"import {module}; "
                    "print(signal.getsignal(signal.SIGUSR1) is signal.SIG_IGN)"
                )
                proc = subprocess.run(
                    [sys.executable, "-c", code],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                self.assertEqual(proc.stdout.strip(), "True", proc.stderr)


if __name__ == "__main__":
    unittest.main()
