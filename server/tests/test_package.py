"""Tests for tmux-status-server package structure and entry points."""

import ast
import os
import sys
import unittest

# Add server directory to path so we can import the module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestInitModule(unittest.TestCase):
    """Test __init__.py contents."""

    def test_version_exists(self):
        """__init__.py exports __version__."""
        import tmux_status_server

        self.assertTrue(hasattr(tmux_status_server, "__version__"))

    def test_version_value(self):
        """__version__ is '0.1.0'."""
        import tmux_status_server

        self.assertEqual(tmux_status_server.__version__, "0.1.0")

    def test_version_is_string(self):
        """__version__ is a string."""
        import tmux_status_server

        self.assertIsInstance(tmux_status_server.__version__, str)

    def test_init_file_exists(self):
        """__init__.py file exists on disk."""
        init_path = os.path.join(
            os.path.dirname(__file__), "..", "tmux_status_server", "__init__.py"
        )
        self.assertTrue(os.path.isfile(init_path))


class TestMainModule(unittest.TestCase):
    """Test __main__.py contents."""

    def test_main_file_exists(self):
        """__main__.py file exists on disk."""
        main_path = os.path.join(
            os.path.dirname(__file__), "..", "tmux_status_server", "__main__.py"
        )
        self.assertTrue(os.path.isfile(main_path))

    def test_main_function_importable(self):
        """main() function can be imported from __main__."""
        from tmux_status_server.__main__ import main

        self.assertTrue(callable(main))

    def test_main_function_exists_in_ast(self):
        """__main__.py defines a main() function at module level."""
        main_path = os.path.join(
            os.path.dirname(__file__), "..", "tmux_status_server", "__main__.py"
        )
        with open(main_path) as f:
            tree = ast.parse(f.read())

        func_names = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
        ]
        self.assertIn("main", func_names)

    def test_main_calls_parse_args(self):
        """main() calls parse_args from the config module."""
        main_path = os.path.join(
            os.path.dirname(__file__), "..", "tmux_status_server", "__main__.py"
        )
        with open(main_path) as f:
            source = f.read()
        self.assertIn("parse_args", source)

    def test_main_calls_warn_if_exposed(self):
        """main() calls warn_if_exposed from the config module."""
        main_path = os.path.join(
            os.path.dirname(__file__), "..", "tmux_status_server", "__main__.py"
        )
        with open(main_path) as f:
            source = f.read()
        self.assertIn("warn_if_exposed", source)

    def test_main_imports_config(self):
        """__main__.py imports from tmux_status_server.config."""
        main_path = os.path.join(
            os.path.dirname(__file__), "..", "tmux_status_server", "__main__.py"
        )
        with open(main_path) as f:
            tree = ast.parse(f.read())

        config_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and "config" in node.module:
                    imported_names = [alias.name for alias in node.names]
                    config_imports.extend(imported_names)

        self.assertIn("parse_args", config_imports)
        self.assertIn("warn_if_exposed", config_imports)

    def test_main_has_if_name_main_guard(self):
        """__main__.py has an ``if __name__ == '__main__'`` guard."""
        main_path = os.path.join(
            os.path.dirname(__file__), "..", "tmux_status_server", "__main__.py"
        )
        with open(main_path) as f:
            source = f.read()
        self.assertIn('if __name__ == "__main__"', source)

    def test_main_exits_with_nonzero(self):
        """Placeholder main() exits with non-zero (server not yet implemented)."""
        from tmux_status_server.__main__ import main

        with self.assertRaises(SystemExit) as cm:
            main()
        self.assertNotEqual(cm.exception.code, 0)


class TestPyprojectToml(unittest.TestCase):
    """Test pyproject.toml contents."""

    def setUp(self):
        self.pyproject_path = os.path.join(
            os.path.dirname(__file__), "..", "pyproject.toml"
        )
        with open(self.pyproject_path) as f:
            self.content = f.read()

    def test_pyproject_exists(self):
        """pyproject.toml exists on disk."""
        self.assertTrue(os.path.isfile(self.pyproject_path))

    def test_project_name(self):
        """pyproject.toml declares name = 'tmux-status-server'."""
        self.assertIn('name = "tmux-status-server"', self.content)

    def test_requires_python(self):
        """pyproject.toml declares requires-python >= 3.10."""
        self.assertIn('requires-python = ">=3.10"', self.content)

    def test_bottle_dependency(self):
        """pyproject.toml declares bottle>=0.12.25 dependency."""
        self.assertIn('"bottle>=0.12.25"', self.content)

    def test_curl_cffi_dependency(self):
        """pyproject.toml declares curl_cffi>=0.5 dependency."""
        self.assertIn('"curl_cffi>=0.5"', self.content)

    def test_console_script_entry_point(self):
        """pyproject.toml declares tmux-status-server console script."""
        self.assertIn("tmux-status-server", self.content)
        self.assertIn("[project.scripts]", self.content)

    def test_project_section_exists(self):
        """pyproject.toml has a [project] section."""
        self.assertIn("[project]", self.content)

    def test_build_system_section_exists(self):
        """pyproject.toml has a [build-system] section."""
        self.assertIn("[build-system]", self.content)


class TestModuleRunnable(unittest.TestCase):
    """Test that python -m tmux_status_server is runnable."""

    def test_python_m_invocation(self):
        """python -m tmux_status_server exits (placeholder) without crashing."""
        import subprocess

        result = subprocess.run(
            [sys.executable, "-m", "tmux_status_server"],
            capture_output=True,
            text=True,
            cwd=os.path.join(os.path.dirname(__file__), ".."),
            timeout=10,
        )
        # The placeholder main() should exit with code 1
        self.assertEqual(result.returncode, 1)
        # Should not produce a traceback
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
