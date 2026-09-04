"""Regression tests for TS-52: SIGUSR1 must never be fatal during a console
script's startup window.

``tmux_status_server.renderd_entry`` is the ``tmux-status-renderd`` console
script's target. Its whole purpose is to arm ``SIG_IGN`` for SIGUSR1 before
anything else in this package is imported, closing the startup race where a
poke landing during interpreter/module import would terminate the daemon
instead of waking it. This is a behavioral (subprocess) proof, not just a
source-level one, since a static check alone cannot catch e.g. a second
``signal.signal`` call re-arming the default handler afterward.
"""

import os
import subprocess
import sys
import unittest

SERVER_ROOT = os.path.join(os.path.dirname(__file__), "..")


class TestRenderdEntryArmsSigusr1Behaviorally(unittest.TestCase):
    """Stdlib-only: prove the disposition is actually SIG_IGN post-import."""

    def test_import_leaves_sigusr1_ignored(self):
        code = (
            "import sys, signal; "
            f"sys.path.insert(0, {SERVER_ROOT!r}); "
            "import tmux_status_server.renderd_entry; "
            "print(signal.getsignal(signal.SIGUSR1) is signal.SIG_IGN)"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True,
        )
        self.assertEqual(proc.stdout.strip(), "True", proc.stderr)


if __name__ == "__main__":
    unittest.main()
