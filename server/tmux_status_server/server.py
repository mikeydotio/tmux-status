"""
HTTP server module for tmux-status-server.

Provides QuotaServer class with Bottle app, /quota and /health endpoints,
API key authentication via hmac.compare_digest, background poll thread,
and signal handling (SIGTERM/SIGINT/SIGUSR1).

Bottle is imported lazily inside methods to avoid import-time dependency
on the package (mirrors the curl_cffi pattern in scraper.py).
"""

import hmac
import json
import logging
import os
import signal
import threading
import time

from tmux_status_server import __version__
from tmux_status_server.config import parse_args, warn_if_exposed
from tmux_status_server.scraper import _error_bridge, fetch_quota, read_session_key

logger = logging.getLogger(__name__)


class QuotaServer:
    """HTTP server that polls claude.ai for quota data and serves it via REST.

    Attributes:
        host: Address to bind the HTTP server.
        port: Port to bind the HTTP server.
        key_file: Path to the claude.ai session key JSON file.
        api_key_file: Optional path to API key file for client auth.
        interval: Scrape interval in seconds.
    """

    def __init__(self, host, port, key_file, api_key_file, interval):
        self.host = host
        self.port = port
        self.key_file = key_file
        self.api_key_file = api_key_file
        self.interval = interval

        self._cached_data = None
        self._last_scrape_ok = False
        self._start_time = time.time()
        self._shutdown = threading.Event()
        self._wake = threading.Event()
        self._api_key = None
        self._poll_thread = None

        self._app = self._create_app()

    def _load_api_key(self):
        """Load API key from file, if configured."""
        if self.api_key_file is None:
            return None
        try:
            with open(self.api_key_file) as f:
                key = f.read().strip()
            if not key:
                logger.warning("API key file is empty: %s", self.api_key_file)
                return None
            return key
        except OSError:
            logger.warning("Could not read API key file: %s", self.api_key_file)
            return None

    def _create_app(self):
        """Create and configure the Bottle app with routes and hooks."""
        from bottle import Bottle, request, response, abort
        from bottle import run as _bottle_run

        self._bottle_run = _bottle_run
        app = Bottle()

        @app.hook("before_request")
        def check_auth():
            if self._api_key is None:
                return
            if request.path == "/health":
                return
            provided = request.get_header("X-API-Key")
            if provided is None or not hmac.compare_digest(provided, self._api_key):
                abort(401, json.dumps({"error": "invalid_or_missing_api_key"}))

        @app.route("/quota")
        def quota():
            response.content_type = "application/json"
            if self._cached_data is None:
                response.status = 503
                return json.dumps({
                    "status": "starting",
                    "five_hour": {"utilization": "X", "resets_at": None},
                    "seven_day": {"utilization": "X", "resets_at": None},
                    "timestamp": int(time.time()),
                    "error": "no_data_yet",
                })
            return json.dumps(self._cached_data)

        @app.route("/health")
        def health():
            response.content_type = "application/json"
            uptime = time.time() - self._start_time
            if self._cached_data is not None and self._last_scrape_ok:
                status = "ok"
            elif self._cached_data is not None:
                status = "degraded"
            else:
                status = "error"
            return json.dumps({
                "status": status,
                "uptime_seconds": int(uptime),
                "version": __version__,
            })

        @app.error(404)
        def error404(err):
            response.content_type = "application/json"
            return json.dumps({"error": "not_found"})

        @app.error(500)
        def error500(err):
            response.content_type = "application/json"
            return json.dumps({"error": "internal_error"})

        return app

    def _do_scrape(self):
        """Perform a single scrape cycle. Re-reads session key each time."""
        key_data = read_session_key(self.key_file)
        if "error" in key_data:
            logger.error("Session key error: %s", key_data["error"])
            self._cached_data = _error_bridge(key_data["error"], key_data["error"])
            self._last_scrape_ok = False
            return

        session_key = key_data["sessionKey"]
        try:
            result = fetch_quota(session_key)
            self._cached_data = result
            if result.get("status") == "ok":
                self._last_scrape_ok = True
                logger.info("Scrape successful")
            else:
                self._last_scrape_ok = False
                logger.warning("Scrape returned status: %s", result.get("status"))
        except Exception:
            logger.exception("Scrape failed")
            self._cached_data = _error_bridge("upstream_error", "upstream_error")
            self._last_scrape_ok = False

    def _poll_loop(self):
        """Background poll loop. Runs first scrape immediately, then at interval."""
        self._do_scrape()
        while not self._shutdown.is_set():
            self._wake.wait(timeout=self.interval)
            self._wake.clear()
            if self._shutdown.is_set():
                break
            self._do_scrape()

    def _handle_sigterm(self, signum, frame):
        """Handle SIGTERM/SIGINT: set shutdown flag."""
        logger.info("Received signal %d, shutting down", signum)
        self._shutdown.set()
        self._wake.set()

    def _handle_sigusr1(self, signum, frame):
        """Handle SIGUSR1: wake poll thread for immediate scrape."""
        logger.info("Received SIGUSR1, triggering immediate scrape")
        self._wake.set()

    def run(self):
        """Start the server: load API key, start poll thread, run Bottle."""
        self._api_key = self._load_api_key()
        self._start_time = time.time()

        signal.signal(signal.SIGTERM, self._handle_sigterm)
        signal.signal(signal.SIGINT, self._handle_sigterm)
        signal.signal(signal.SIGUSR1, self._handle_sigusr1)

        self._poll_thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="quota-poll"
        )
        self._poll_thread.start()

        logger.info(
            "Starting HTTP server on %s:%d (interval=%ds)",
            self.host,
            self.port,
            self.interval,
        )
        self._bottle_run(self._app, host=self.host, port=self.port, quiet=True)


def main():
    """Entry point for tmux-status-server.

    Parses CLI arguments, sets up logging, validates the bind address,
    and starts the QuotaServer.
    """
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    warn_if_exposed(args)

    server = QuotaServer(
        host=args.host,
        port=args.port,
        key_file=args.key_file,
        api_key_file=args.api_key_file,
        interval=args.interval,
    )
    server.run()
