"""Single-instance guard for the tmux-status render daemon.

The render daemon must never run more than one copy at a time: a second
instance would double the work (process-table snapshots, transcript parsing,
git calls) and races on the per-pane cache files. launchd/systemd already
keep a single managed instance, but a manually launched copy (or a reload
race) must exit immediately rather than pile on.

This uses an advisory ``fcntl.flock`` held for the process lifetime. The
kernel releases the lock automatically when the process exits or crashes, so
there is no stale-pidfile cleanup to get wrong.
"""

import fcntl
import logging
import os

logger = logging.getLogger(__name__)


def acquire_singleton(lock_path):
    """Acquire the single-instance lock.

    Args:
        lock_path: Path to the lock file. Its parent directory is created
            if missing.

    Returns:
        The open lock file object on success — keep a reference to it for the
        process lifetime so the lock stays held. Returns ``None`` if another
        instance already holds the lock (the caller should exit 0).
    """
    parent = os.path.dirname(lock_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    # Open (not truncate) so a concurrent holder's pid line is preserved until
    # we actually win the lock.
    fd = open(lock_path, "a+")
    try:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fd.close()
        logger.info("Another tmux-status-renderd holds %s; exiting", lock_path)
        return None
    except OSError:
        # Locking unsupported (e.g. some network filesystems): degrade to
        # running rather than refusing to start. The thin readers tolerate a
        # racing second writer because cache writes are atomic.
        logger.warning("flock unavailable on %s; continuing without guard", lock_path)
        return fd

    # We hold the lock — record our pid for humans inspecting the file.
    try:
        fd.seek(0)
        fd.truncate()
        fd.write(f"{os.getpid()}\n")
        fd.flush()
    except OSError:
        pass
    return fd
