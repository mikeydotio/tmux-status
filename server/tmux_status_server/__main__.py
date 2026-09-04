"""Entry point for ``python -m tmux_status_server``."""

import signal

# server.py installs the real wake handler in QuotaServer.run(), after its
# imports and setup. Neutralize SIGUSR1 before loading it so the console script
# cannot be terminated in that startup window (TS-52).
signal.signal(signal.SIGUSR1, signal.SIG_IGN)

from tmux_status_server.server import main as _server_main  # noqa: E402


def main():
    """Launch the tmux-status-server.

    Delegates to the server module's main() which parses CLI arguments,
    validates the bind address, and starts the HTTP server with background
    quota polling.
    """
    _server_main()


if __name__ == "__main__":
    main()
