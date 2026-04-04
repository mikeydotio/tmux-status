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
DEFAULT_KEY_FILE = os.path.join("~", ".config", "tmux-status", "claude-usage-key.json")


def parse_args(argv=None):
    """Parse CLI arguments for tmux-status-server.

    Args:
        argv: Argument list to parse. Defaults to sys.argv[1:] when None.

    Returns:
        argparse.Namespace with host, port, key_file, api_key_file,
        interval, and log_level attributes.
    """
    parser = argparse.ArgumentParser(
        description="Scrape claude.ai for quota data and serve via HTTP REST API.",
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
        "--key-file",
        default=DEFAULT_KEY_FILE,
        help="Path to claude.ai session key JSON file (default: %(default)s)",
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
        help="Scrape interval in seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--log-level",
        default=DEFAULT_LOG_LEVEL,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: %(default)s)",
    )

    args = parser.parse_args(argv)

    # Expand ~ in file paths
    args.key_file = os.path.expanduser(args.key_file)
    if args.api_key_file is not None:
        args.api_key_file = os.path.expanduser(args.api_key_file)

    return args


def warn_if_exposed(args):
    """Log a warning when the server binds to a non-localhost address
    without API key authentication configured.

    Args:
        args: Parsed argparse.Namespace from parse_args().
    """
    if args.host != "127.0.0.1" and args.api_key_file is None:
        logger.warning(
            "Listening on %s:%d with NO authentication.", args.host, args.port
        )
