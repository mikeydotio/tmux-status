"""Tests for the render daemon's single-instance flock guard."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tmux_status_server.singleton import acquire_singleton  # noqa: E402


class TestSingleton(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.lock = os.path.join(self.tmp, "renderd.lock")

    def test_first_acquire_succeeds(self):
        fd = acquire_singleton(self.lock)
        self.assertIsNotNone(fd)
        fd.close()

    def test_second_acquire_blocks(self):
        fd1 = acquire_singleton(self.lock)
        self.assertIsNotNone(fd1)
        try:
            fd2 = acquire_singleton(self.lock)
            self.assertIsNone(fd2, "second concurrent acquire must fail")
        finally:
            fd1.close()

    def test_lock_released_on_close(self):
        fd1 = acquire_singleton(self.lock)
        self.assertIsNotNone(fd1)
        fd1.close()  # release
        fd2 = acquire_singleton(self.lock)
        self.assertIsNotNone(fd2, "lock should be re-acquirable after close")
        fd2.close()

    def test_creates_parent_directory(self):
        nested = os.path.join(self.tmp, "render", "sub", "renderd.lock")
        fd = acquire_singleton(nested)
        self.assertIsNotNone(fd)
        self.assertTrue(os.path.isdir(os.path.dirname(nested)))
        fd.close()

    def test_writes_pid(self):
        fd = acquire_singleton(self.lock)
        self.assertIsNotNone(fd)
        fd.close()
        with open(self.lock) as f:
            self.assertEqual(f.read().strip(), str(os.getpid()))


if __name__ == "__main__":
    unittest.main()
