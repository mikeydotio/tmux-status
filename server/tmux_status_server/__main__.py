"""Entry point for ``python -m tmux_status_server``."""

import logging
import sys

from tmux_status_server.config import parse_args, warn_if_exposed

logger = logging.getLogger(__name__)


def main():
    """Launch the tmux-status-server.

    Parses CLI arguments, validates the bind address, and starts the HTTP
    server.  The actual server implementation will be provided by the
    server module (TS-6 / T2.1); until then this placeholder validates the
    config pipeline and exits.
    """
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level))
    warn_if_exposed(args)

    logger.info(
        "tmux-status-server is not yet implemented. "
        "Config parsed: host=%s port=%d interval=%d",
        args.host,
        args.port,
        args.interval,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
