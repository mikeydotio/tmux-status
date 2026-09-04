"""Console-script entry point for ``tmux-status-renderd``.

This module's only job before delegating to :mod:`tmux_status_server.render`
is to make SIGUSR1 a no-op — and it must do that *before* anything else in
this package is imported.

SIGUSR1's default disposition is to terminate the process. ``render.py``
installs its own SIGUSR1 handling (the daemon's real wake-up handler, or
``SIG_IGN`` for ``--once``) but only after it has finished importing — a ~60KB
module — and, for the daemon path, after ``acquire_singleton()`` as well.
``tmux-status-poke`` fires SIGUSR1 at this process on ordinary tmux/statusLine
events; one landing in that startup window kills the daemon instead of waking
it (TS-52), and KeepAlive/systemd restart is not guaranteed to notice or
recover it.

Arming ``SIG_IGN`` here, as the first statement executed, before
``tmux_status_server.render`` (and therefore its imports) is even loaded,
narrows the fatal window down to the part of process startup that happens
before any Python bytecode of ours runs at all — unreachable from here.
``render.main()`` still installs the real wake handler for the daemon path,
and keeps its own defense-in-depth ``SIG_IGN`` for ``--once`` and for callers
that invoke ``render.main()`` directly (e.g. tests).

This mutation belongs in an entry *module*, not at module scope in
``render.py`` itself: ``render.py`` is imported by the test suite and other
tooling, and a library module must not mutate process-global signal state
merely by being imported — doing so would silently strip SIGUSR1 handling
from whatever process imported it for unrelated reasons.
"""

import signal

signal.signal(signal.SIGUSR1, signal.SIG_IGN)

from tmux_status_server.render import main  # noqa: E402


if __name__ == "__main__":
    main()
