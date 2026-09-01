"""
Configuration module for tmux-status-server.

Provides argparse-based CLI configuration with secure defaults.
All dependencies are stdlib only (argparse, logging, os, pathlib).
"""

import argparse
import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7850
DEFAULT_INTERVAL = 300
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_USAGE_SOCKET = "tmux-status-usage"
DEFAULT_BOOT_TIMEOUT = 45.0


def parse_args(argv=None):
    """Parse CLI arguments for tmux-status-server.

    Args:
        argv: Argument list to parse. Defaults to sys.argv[1:] when None.

    Returns:
        argparse.Namespace with host, port, api_key_file, interval,
        usage_socket, usage_cwd, boot_timeout, and log_level attributes.
    """
    parser = argparse.ArgumentParser(
        description="Collect Claude usage data from the CLI and serve via HTTP REST API.",
    )

    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help="Address to bind the HTTP server (default: %(default)s)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="Port to bind the HTTP server (default: %(default)s)",
    )
    parser.add_argument(
        "--usage-socket",
        default=DEFAULT_USAGE_SOCKET,
        help=(
            "Dedicated tmux socket name for the headless usage capture. "
            "MUST NOT be the user's default server (default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--usage-cwd",
        default=None,
        help="Working directory for the headless CLI session (default: process cwd)",
    )
    parser.add_argument(
        "--boot-timeout",
        type=float,
        default=DEFAULT_BOOT_TIMEOUT,
        help="Seconds to wait for the CLI TUI to accept input (default: %(default)s)",
    )
    parser.add_argument(
        "--api-key-file",
        default=None,
        help="Path to API key file for authenticating client requests (default: None)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL,
        help="Usage collection interval in seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--log-level",
        default=DEFAULT_LOG_LEVEL,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: %(default)s)",
    )

    args = parser.parse_args(argv)

    if args.interval < 30:
        parser.error("--interval must be at least 30 seconds")

    if args.usage_socket == "default":
        parser.error(
            "--usage-socket must not be 'default': the capture session must be "
            "isolated from the user's tmux server"
        )

    # Expand ~ in file paths
    if args.usage_cwd is not None:
        args.usage_cwd = os.path.expanduser(args.usage_cwd)
    if args.api_key_file is not None:
        args.api_key_file = os.path.expanduser(args.api_key_file)

    return args


def warn_if_exposed(args):
    """Log a warning when the server binds to a non-localhost address
    without API key authentication configured.

    Args:
        args: Parsed argparse.Namespace from parse_args().
    """
    if args.host not in ("127.0.0.1", "localhost", "::1") and args.api_key_file is None:
        logger.warning(
            "Listening on %s:%d with NO authentication.", args.host, args.port
        )
