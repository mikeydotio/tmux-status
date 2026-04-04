"""Entry point for ``python -m tmux_status_server``."""

from tmux_status_server.server import main as _server_main


def main():
    """Launch the tmux-status-server.

    Delegates to the server module's main() which parses CLI arguments,
    validates the bind address, and starts the HTTP server with background
    quota polling.
    """
    _server_main()


if __name__ == "__main__":
    main()
