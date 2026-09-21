"""
HTTP server module for tmux-status-server.

Provides QuotaServer class with Bottle app, /quota and /health endpoints,
API key authentication via hmac.compare_digest, background poll thread,
and signal handling (SIGTERM/SIGINT/SIGUSR1).

Bottle is imported lazily inside methods to avoid an import-time dependency
on the package.
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
from tmux_status_server.cli_usage import (
    CliUsageCollector,
    HeadlessClaudeSession,
    error_bridge,
)

logger = logging.getLogger(__name__)

# Degradation thresholds. A reading older than FRESH_MAX is real but no longer
# current; older than GOOD_MAX it is dropped entirely rather than shown as if it
# still meant something. See docs/spec/quota-resilience.md.
QUOTA_FRESH_MAX = 300.0
QUOTA_GOOD_MAX = 86400.0
# Sustained failure re-boots a 199MB CLI for nothing. The 2026-09-16 outage ran
# 2385 such boots before anyone noticed, so failures buy time between attempts.
QUOTA_BACKOFF_MAX = 3600.0
QUOTA_ESCALATE_AFTER = 3


class QuotaServer:
    """HTTP server that collects Claude usage data and serves it via REST.

    Attributes:
        host: Address to bind the HTTP server.
        port: Port to bind the HTTP server.
        api_key_file: Optional path to API key file for client auth.
        interval: Collection interval in seconds.
        collector: Usage collector; defaults to CliUsageCollector.
    """

    def __init__(self, host, port, api_key_file, interval, collector=None,
                 fresh_max=QUOTA_FRESH_MAX, good_max=QUOTA_GOOD_MAX,
                 backoff_max=QUOTA_BACKOFF_MAX,
                 escalate_after=QUOTA_ESCALATE_AFTER):
        self.host = host
        self.port = port
        self.api_key_file = api_key_file
        self.interval = interval
        self.collector = collector or CliUsageCollector()
        self.fresh_max = fresh_max
        self.good_max = good_max
        self.backoff_max = backoff_max
        self.escalate_after = escalate_after

        # _cached_data holds the last *successful* reading only. A failure must
        # never replace it: doing so is what turned two upstream hiccups into a
        # 3-hour and a 4-day blackout with no numbers and no age (TS-56).
        self._cached_data = None
        self._cached_at = None
        self._last_error = None
        self._consecutive_failures = 0
        self._escalated = False
        self._last_collect_ok = False
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
            bridge = self._current_bridge()
            if bridge is None:
                response.status = 503
                return json.dumps({
                    "status": "starting",
                    "five_hour": {"utilization": "X", "resets_at": None},
                    "seven_day": {"utilization": "X", "resets_at": None},
                    "timestamp": int(time.time()),
                    "error": "no_data_yet",
                    "age_seconds": None,
                })
            if self._cached_data is None:
                response.status = 503
            return json.dumps(bridge)

        @app.route("/health")
        def health():
            response.content_type = "application/json"
            uptime = time.time() - self._start_time
            if self._cached_data is not None and self._last_collect_ok:
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

        @app.error(401)
        def error401(err):
            response.content_type = "application/json"
            return json.dumps({"error": "invalid_or_missing_api_key"})

        @app.error(404)
        def error404(err):
            response.content_type = "application/json"
            return json.dumps({"error": "not_found"})

        @app.error(500)
        def error500(err):
            response.content_type = "application/json"
            return json.dumps({"error": "internal_error"})

        return app

    def _do_collect(self):
        """Perform a single usage-collection cycle.

        The collector contains its own failure handling and returns an error
        bridge rather than raising; the extra guard here is for a collector
        that breaks its contract, so the poll thread can never die.
        """
        try:
            result = self.collector.collect()
        except Exception:
            logger.exception("Collector raised")
            result = error_bridge("collector_crashed")

        if result.get("status") == "ok":
            self._cached_data = result
            self._cached_at = time.time()
            self._last_error = None
            self._consecutive_failures = 0
            self._escalated = False
            self._last_collect_ok = True
            logger.info("Usage collection successful")
            return

        self._last_collect_ok = False
        self._last_error = result.get("error", "unknown")
        self._consecutive_failures += 1
        logger.warning("Usage collection failed: %s", self._last_error)

        # Loud exactly once per outage: a WARNING per 5-minute poll is how four
        # days of failure stayed invisible.
        if self._consecutive_failures >= self.escalate_after and not self._escalated:
            self._escalated = True
            logger.error(
                "Quota collection failing persistently: %s "
                "(%d consecutive failures; last good reading %s)",
                self._last_error,
                self._consecutive_failures,
                "never" if self._cached_at is None
                else f"{int(time.time() - self._cached_at)}s ago",
            )

    def _current_bridge(self):
        """Return the bridge to serve, or None if nothing was ever collected.

        Degrades in three steps rather than collapsing straight to ``X``:
        fresh numbers, real-but-stale numbers carrying their age and the reason
        they stopped refreshing, then — only once they are too old to mean
        anything — an error that still states how long we have been blind.
        """
        if self._cached_data is None:
            if self._last_error is None:
                return None
            return dict(error_bridge(self._last_error), age_seconds=None)

        # Freshness is a property of the reading's age, not of the last
        # attempt: a collection that just failed over a 30-second-old number
        # has not made that number wrong.
        age = 0 if self._cached_at is None else int(time.time() - self._cached_at)
        if age > self.good_max:
            return dict(error_bridge(self._last_error or "quota_unavailable"),
                        age_seconds=age)
        bridge = dict(self._cached_data, age_seconds=age)
        if age <= self.fresh_max:
            bridge["status"] = "ok"
            bridge.pop("error", None)
        else:
            bridge["status"] = "stale"
            if self._last_error:
                bridge["error"] = self._last_error
        return bridge

    def _next_interval(self):
        """Poll interval for the next cycle, backed off by consecutive failures."""
        if not self._consecutive_failures:
            return self.interval
        backed_off = self.interval * (2 ** self._consecutive_failures)
        return min(backed_off, self.backoff_max)

    def _poll_loop(self):
        """Background poll loop. Collects immediately, then at each interval."""
        self._do_collect()
        while not self._shutdown.is_set():
            self._wake.wait(timeout=self._next_interval())
            self._wake.clear()
            if self._shutdown.is_set():
                break
            self._do_collect()

    def _handle_sigterm(self, signum, frame):
        """Handle SIGTERM/SIGINT: raise SystemExit to stop serve_forever()."""
        logger.info("Received signal %d, shutting down", signum)
        self._shutdown.set()
        self._wake.set()
        raise SystemExit(0)

    def _handle_sigusr1(self, signum, frame):
        """Handle SIGUSR1: wake poll thread for an immediate collection."""
        logger.info("Received SIGUSR1, triggering immediate collection")
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

    def session_factory():
        """Build a capture session on the configured isolated socket."""
        return HeadlessClaudeSession(
            socket_name=args.usage_socket,
            cwd=args.usage_cwd,
            boot_timeout=args.boot_timeout,
            inherit_auth_env=args.usage_inherit_auth_env,
        )

    server = QuotaServer(
        host=args.host,
        port=args.port,
        api_key_file=args.api_key_file,
        interval=args.interval,
        collector=CliUsageCollector(session_factory=session_factory),
    )
    server.run()
