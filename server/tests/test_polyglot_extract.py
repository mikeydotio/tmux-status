"""Tests for the polyglot extraction harness."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from polyglot_extract import extract_function, load_function, SCRIPT_PATH


class TestExtractionHarness(unittest.TestCase):
    """Test that the extraction harness works correctly."""

    def test_script_exists(self):
        """The polyglot script exists at the expected path."""
        self.assertTrue(os.path.isfile(SCRIPT_PATH))

    def test_extract_maybe_fetch_quota_source(self):
        """Extracts _maybe_fetch_quota source code."""
        source = extract_function('_maybe_fetch_quota')
        self.assertIn('def _maybe_fetch_quota(', source)
        self.assertIn('urllib.request.Request', source)
        self.assertIn('os.replace', source)

    def test_extract_function_is_valid_python(self):
        """Extracted function compiles as valid Python."""
        source = extract_function('_maybe_fetch_quota')
        compile(source, '<test>', 'exec')  # should not raise SyntaxError

    def test_load_function_returns_callable(self):
        """load_function returns a callable."""
        fn = load_function('_maybe_fetch_quota')
        self.assertTrue(callable(fn))

    def test_function_signature(self):
        """Extracted function has the expected parameters."""
        import inspect
        fn = load_function('_maybe_fetch_quota')
        params = list(inspect.signature(fn).parameters.keys())
        self.assertEqual(params, ['source_url', 'api_key', 'cache_ttl', 'cache_path'])

    def test_noop_when_no_source_url(self):
        """Returns None when source_url is empty."""
        fn = load_function('_maybe_fetch_quota')
        result = fn('', None, 0, '/tmp/test-cache.json')
        self.assertIsNone(result)

    def test_nonexistent_function_raises(self):
        """Extracting a nonexistent function raises ValueError."""
        with self.assertRaises(ValueError):
            extract_function('nonexistent_function_xyz')


if __name__ == '__main__':
    unittest.main()
