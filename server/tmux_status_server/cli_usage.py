"""
Usage collection by driving the Claude Code CLI in a headless tmux session.

Replaces the former claude.ai HTTP scraper. The CLI is already authenticated,
so there is no session key to expire, be revoked, or need re-minting — the
failure mode that made this module necessary.

The collection path is:

    tmux -L <socket> new-session -d 'claude --ax-screen-reader'
      -> send "/usage"
      -> capture-pane
      -> parse
      -> kill-server

``--ax-screen-reader`` is deliberate: it renders flat labelled text with no
box-drawing, progress-bar glyphs, or column padding, which is far more stable
to parse than the default TUI.

**Isolation invariant:** capture MUST run on a dedicated tmux socket, never the
user's default server. On the default server the pane would be enumerated by
``render.py``'s ``tmux list-panes -a`` (producing a bogus per-pane cache), would
consume tmux-server file descriptors against the documented 256 soft limit, and
would be detached and transport-reaped by ``tmux-status-prune-clients``.

**Geometry invariant:** capture at a fixed 120x45. Wrapping width determines
where lines break, and therefore whether the golden fixtures still match.
"""

import logging
import os
import re
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

# The daemon runs under launchd (macOS) / systemd (Linux), whose PATH omits
# both Homebrew and ~/.local/bin. Resolving `tmux` or `claude` against the
# inherited PATH alone returns None there and every collection fails. Mirrors
# render.py's _EXTRA_PATH, plus ~/.local/bin, where `claude` installs.
_EXTRA_PATH = [
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "~/.local/bin",
    "/usr/bin",
    "/bin",
    "/usr/sbin",
    "/sbin",
]

DEFAULT_SOCKET = "tmux-status-usage"
DEFAULT_WIDTH = 120
DEFAULT_HEIGHT = 45
DEFAULT_BOOT_TIMEOUT = 45.0
DEFAULT_SCREEN_TIMEOUT = 30.0
_POLL_INTERVAL = 0.5

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

# "16% 16% used" — the bar's aria-label repeats the figure before the word.
# Anchored to "used" so narrative percentages ("89% of your usage was...")
# and table cells ("/reconcile-pr  7%") can never match.
_PCT_RE = re.compile(r"(?<![\d.])(\d{1,3})%\s+used\b")

# "Resets 3:50pm (America/Los_Angeles)"
# "Resets Sep 3 at 9am (America/Los_Angeles)"
_RESET_RE = re.compile(
    r"^Resets\s+"
    r"(?:(?P<month>[A-Z][a-z]{2})\s+(?P<day>\d{1,2})\s+at\s+)?"
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>am|pm)"
    r"(?:\s*\((?P<tz>[^)]+)\))?",
    re.IGNORECASE,
)

_SESSION_HEADING = "Current session"
_WEEK_HEADING = "Current week (all models)"
_MODEL_WEEK_RE = re.compile(r"^Current week \((?P<label>(?!all models)[^)]+)\)\s*$")

_LOGIN_MARKERS = (
    "Select login method",
    "Welcome to Claude Code",
    "Anthropic Console account",
    # The TUI can boot fully and still be unauthenticated, showing this in the
    # footer. Without it the collector waits out the whole screen timeout and
    # reports an opaque usage_screen_timeout instead of naming the real cause.
    "Not logged in",
)

# The input-mode footer, which appears only once the input box accepts
# keystrokes. Measured: the startup banner paints ~3s earlier, and keys sent in
# that window are silently dropped. Do not key readiness off the banner, and do
# not use the "effort:" hint — it is transient and clears after ~10s.
_READY_MARKER = "shift+tab"

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def search_path():
    """Return PATH augmented with the bin dirs launchd/systemd omit.

    Never mutates ``os.environ``: the collector runs on the server's poll
    thread, and a global mutation there would race the rest of the process.
    """
    current = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d]
    extra = [os.path.expanduser(d) for d in _EXTRA_PATH]
    return os.pathsep.join([d for d in extra if d not in current] + current)


class UsageError(Exception):
    """A usage-collection failure carrying a machine-readable cause code.

    The code names the real cause (boot timeout, parse failure, missing binary)
    rather than collapsing everything into one opaque status, so a future CLI
    layout change is diagnosable from logs alone.
    """

    def __init__(self, code, message=None):
        super().__init__(message or code)
        self.code = code


def error_bridge(error_code):
    """Build an error-state quota bridge whose windows render as ``X``.

    ``status`` is always the literal ``"error"`` — never the code itself, which
    is what the previous scraper did, leaving ``render.py``'s ``elif
    quota_status == "error"`` branch permanently unreachable.
    """
    return {
        "status": "error",
        "five_hour": {"utilization": "X", "resets_at": None},
        "seven_day": {"utilization": "X", "resets_at": None},
        "model_week": None,
        "error": error_code,
        "timestamp": int(time.time()),
    }


@dataclass(frozen=True)
class ResetSpec:
    """A reset time as the Usage screen states it, before calendar resolution.

    The screen gives human strings with no year, and often no date at all
    (``3:50pm``). Capturing the structure separately from resolving it keeps
    the ambiguous next-occurrence arithmetic pure and independently testable.
    """

    raw: str
    tzname: str
    hour: int
    minute: int
    month: Optional[int] = None
    day: Optional[int] = None

    def to_iso(self, now=None):
        """Resolve to the next future occurrence as an ISO 8601 string.

        ``render.py``'s ``fmt_reset()`` parses the result with
        ``datetime.fromisoformat``, so the output must always be ISO with an
        offset — never an epoch, which is the Codex path's format.
        """
        try:
            tz = ZoneInfo(self.tzname)
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            # An unrecognised zone must not lose the reading entirely; UTC
            # keeps the value usable and the error visible in the raw string.
            logger.warning("Unknown timezone %r in reset %r", self.tzname, self.raw)
            tz = timezone.utc

        now = datetime.now(tz) if now is None else now.astimezone(tz)

        if self.month is not None and self.day is not None:
            candidate = self._build(now.year, self.month, self.day, tz)
            if candidate < now:
                candidate = self._build(now.year + 1, self.month, self.day, tz)
        else:
            candidate = self._build(now.year, now.month, now.day, tz)
            if candidate < now:
                candidate = candidate + timedelta(days=1)

        return candidate.isoformat()

    def _build(self, year, month, day, tz):
        """Construct the localized reset datetime, tolerating DST gaps.

        A wall-clock time inside a spring-forward gap does not exist; ``fold=0``
        yields a valid instant (offset by at most one hour) rather than raising.
        """
        return datetime(
            year, month, day, self.hour, self.minute, tzinfo=tz, fold=0
        )


@dataclass(frozen=True)
class ParsedUsage:
    """The three usage windows as read off the screen, pre-bridge-mapping."""

    session_pct: float
    week_pct: float
    session_reset: Optional[ResetSpec] = None
    week_reset: Optional[ResetSpec] = None
    model_week_pct: Optional[float] = None
    model_week_label: Optional[str] = None
    model_week_reset: Optional[ResetSpec] = None


class UsageScreenParser:
    """Turns captured Usage-screen text into a :class:`ParsedUsage`.

    Pure: no I/O, no clock, no subprocess. This is what lets the whole parsing
    surface be tested offline against golden fixtures.
    """

    def parse(self, text):
        """Parse a captured screen.

        Raises:
            UsageError: ``cli_not_authenticated`` when a login prompt is showing,
                ``usage_parse_failed`` when either required window is missing.
        """
        if not text or not text.strip():
            raise UsageError("usage_parse_failed", "empty capture")

        clean = _ANSI_RE.sub("", text)

        for marker in _LOGIN_MARKERS:
            if marker in clean:
                raise UsageError("cli_not_authenticated", f"login screen: {marker!r}")

        lines = [ln.rstrip() for ln in clean.splitlines()]

        session = self._section(lines, lambda ln: ln.strip() == _SESSION_HEADING)
        week = self._section(lines, lambda ln: ln.strip() == _WEEK_HEADING)

        missing = [
            name for name, sec in (("Current session", session),
                                   ("Current week (all models)", week))
            if sec is None
        ]
        if missing:
            # A truncated or restyled screen must fail loudly rather than
            # yield a half-populated bridge that renders as plausible numbers.
            raise UsageError(
                "usage_parse_failed", f"missing section(s): {', '.join(missing)}"
            )

        model_pct, model_label, model_reset = self._model_week(lines)

        return ParsedUsage(
            session_pct=session[0],
            session_reset=session[1],
            week_pct=week[0],
            week_reset=week[1],
            model_week_pct=model_pct,
            model_week_label=model_label,
            model_week_reset=model_reset,
        )

    def _section(self, lines, matches_heading):
        """Read the (percentage, reset) pair following a matching heading.

        Scans only until the next section heading, so a percentage belonging to
        a later section can never be attributed to this one.
        """
        for idx, line in enumerate(lines):
            if not matches_heading(line):
                continue
            pct = None
            reset = None
            for follow in lines[idx + 1: idx + 6]:
                stripped = follow.strip()
                # Stop at the next heading unconditionally. Breaking only once a
                # percentage was found would let a section whose own figure is
                # unparseable silently adopt the following section's.
                if self._is_heading(stripped):
                    break
                if pct is None:
                    match = _PCT_RE.search(stripped)
                    if match:
                        value = float(match.group(1))
                        if value > 100:
                            raise UsageError(
                                "usage_parse_failed", f"implausible percentage: {value}"
                            )
                        pct = value
                        continue
                if pct is not None and stripped.startswith("Resets"):
                    reset = self._parse_reset(stripped)
                    break
            if pct is not None:
                return pct, reset
        return None

    @staticmethod
    def _is_heading(line):
        """True when the line starts a different usage section."""
        return line == _SESSION_HEADING or line.startswith("Current week (")

    def _model_week(self, lines):
        """Read the optional per-model weekly window, e.g. ``Current week (Fable)``."""
        for idx, line in enumerate(lines):
            match = _MODEL_WEEK_RE.match(line.strip())
            if not match:
                continue
            label = match.group("label")
            section = self._section(lines[idx:], lambda ln, m=match: ln.strip() == m.group(0))
            if section is None:
                return None, None, None
            return section[0], label, section[1]
        return None, None, None

    @staticmethod
    def _parse_reset(line):
        """Parse a ``Resets ...`` line into a :class:`ResetSpec`, or None."""
        match = _RESET_RE.match(line)
        if not match:
            logger.debug("Unparseable reset line: %r", line)
            return None

        hour = int(match.group("hour")) % 12
        if match.group("ampm").lower() == "pm":
            hour += 12
        minute = int(match.group("minute") or 0)

        month = None
        day = None
        if match.group("month"):
            month = _MONTHS.get(match.group("month").lower())
            day = int(match.group("day"))
            if month is None:
                return None

        return ResetSpec(
            raw=line,
            tzname=match.group("tz") or "UTC",
            hour=hour,
            minute=minute,
            month=month,
            day=day,
        )


class HeadlessClaudeSession:
    """A short-lived ``claude`` TUI on a private tmux socket.

    Used as a context manager so ``kill-server`` runs on every exit path —
    success, parse failure, timeout, or unexpected exception. Leaking a tmux
    server here would leak a Node process with it.
    """

    def __init__(self, socket_name=DEFAULT_SOCKET, cwd=None,
                 width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT,
                 boot_timeout=DEFAULT_BOOT_TIMEOUT,
                 screen_timeout=DEFAULT_SCREEN_TIMEOUT):
        self.socket_name = socket_name
        self.cwd = cwd
        self.width = width
        self.height = height
        self.boot_timeout = boot_timeout
        self.screen_timeout = screen_timeout
        self._started = False
        self._pane_pid = None
        self.tmux_bin = "tmux"
        self.claude_bin = "claude"

    def __enter__(self):
        """Start the isolated tmux server and boot the CLI inside it."""
        path = search_path()
        tmux = shutil.which("tmux", path=path)
        if tmux is None:
            raise UsageError("tmux_unavailable", f"tmux not found on {path}")
        claude = shutil.which("claude", path=path)
        if claude is None:
            raise UsageError("cli_not_found", f"claude not found on {path}")
        self.tmux_bin = tmux
        self.claude_bin = claude

        # Any survivor from a previous crashed run would serve a stale screen.
        self._tmux("kill-server", check=False)

        command = f"{self.claude_bin} --ax-screen-reader --permission-mode plan"
        args = ["new-session", "-d", "-x", str(self.width), "-y", str(self.height)]
        if self.cwd:
            args += ["-c", str(self.cwd)]
        args.append(command)

        result = self._tmux(*args, check=False)
        if result.returncode != 0:
            raise UsageError(
                "tmux_unavailable", f"new-session failed: {result.stderr.strip()}"
            )
        self._started = True
        self._pane_pid = self._read_pane_pid()
        return self

    def __exit__(self, exc_type, exc, tb):
        """Tear the tmux server down unconditionally, then reap the CLI."""
        if self._started:
            self._tmux("kill-server", check=False)
            self._reap(self._pane_pid)
            self._started = False
            self._pane_pid = None
        return False

    def _read_pane_pid(self):
        """Return the pid of the process tmux started in the pane, if available."""
        result = self._tmux(
            "list-panes", "-F", "#{pane_pid}", check=False
        )
        if result.returncode != 0:
            return None
        pid = result.stdout.strip().splitlines()
        try:
            return int(pid[0]) if pid else None
        except ValueError:
            return None

    @staticmethod
    def _reap(pid, timeout=5.0):
        """Ensure the CLI process is gone after the tmux server is killed.

        ``kill-server`` returns before the pane's child has necessarily exited,
        and a child that ignores SIGHUP would survive it entirely — leaking one
        Node process per poll. Wait briefly, then escalate to SIGKILL.
        """
        if not pid:
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except (ProcessLookupError, PermissionError):
                return
            time.sleep(_POLL_INTERVAL)
        try:
            logger.warning("CLI pid %d survived kill-server; sending SIGKILL", pid)
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    def capture_usage_screen(self):
        """Boot-wait, send ``/usage``, and return the captured screen text.

        Raises:
            UsageError: ``cli_boot_timeout`` if the TUI never came up,
                ``usage_screen_timeout`` if the Usage sections never rendered.
        """
        ready_screen = self._wait_for(
            self.is_ready, self.boot_timeout, "cli_boot_timeout"
        )
        # Fail fast on an unauthenticated CLI rather than waiting out the full
        # screen timeout for a Usage view that will never render.
        self._raise_if_unauthenticated(ready_screen)
        self._send_usage_command()

        # Re-send once if the view never opened: a keystroke can still be lost
        # to a redraw. Guarded on the input footer still being visible, so we
        # never type into an already-open Usage view.
        deadline = time.monotonic() + self.screen_timeout
        try:
            return self._wait_for(
                self.shows_usage, self.screen_timeout / 2, "usage_screen_timeout"
            )
        except UsageError:
            if self.is_ready(self._capture()):
                logger.debug("Usage view did not open; re-sending /usage")
                self._send_usage_command()
            remaining = max(_POLL_INTERVAL, deadline - time.monotonic())
            return self._wait_for(self.shows_usage, remaining, "usage_screen_timeout")

    @staticmethod
    def _raise_if_unauthenticated(screen):
        """Raise ``cli_not_authenticated`` when the CLI reports no login."""
        for marker in _LOGIN_MARKERS:
            if marker in screen:
                raise UsageError("cli_not_authenticated", f"CLI reports: {marker!r}")

    @staticmethod
    def is_ready(screen):
        """True once the TUI input box is live and will accept keystrokes."""
        return _READY_MARKER in screen

    @staticmethod
    def shows_usage(screen):
        """True once the Usage view has rendered its window sections."""
        return _WEEK_HEADING in screen

    def _send_usage_command(self):
        """Type ``/usage`` and commit it."""
        self._tmux("send-keys", "-t", "0", "/usage")
        # The slash-command menu needs a beat to resolve before Enter commits it.
        time.sleep(1.0)
        self._tmux("send-keys", "-t", "0", "Enter")

    def _wait_for(self, predicate, timeout, error_code):
        """Poll ``capture-pane`` until ``predicate`` holds or the timeout expires."""
        deadline = time.monotonic() + timeout
        screen = ""
        while time.monotonic() < deadline:
            screen = self._capture()
            if predicate(screen):
                return screen
            time.sleep(_POLL_INTERVAL)
        logger.debug("Timed out (%s); last screen:\n%s", error_code, screen)
        raise UsageError(error_code, f"timed out after {timeout}s")

    def _capture(self):
        """Return the pane's visible text, or empty string if unavailable."""
        result = self._tmux("capture-pane", "-p", "-t", "0", check=False)
        return result.stdout if result.returncode == 0 else ""

    def _tmux(self, *args, check=True):
        """Run one tmux command against this session's private socket."""
        # tmux spawns the CLI through a shell, so the augmented PATH has to
        # reach the child too, not just our own which() lookups.
        return subprocess.run(
            [self.tmux_bin, "-L", self.socket_name, *args],
            capture_output=True,
            text=True,
            check=check,
            timeout=30,
            env={**os.environ, "PATH": search_path()},
        )


class CliUsageCollector:
    """Collects a quota bridge by capturing and parsing the CLI Usage screen."""

    def __init__(self, session_factory=None, parser=None):
        self._session_factory = session_factory or HeadlessClaudeSession
        self._parser = parser or UsageScreenParser()

    def collect(self, now=None):
        """Capture, parse, and map the Usage screen onto a quota bridge dict.

        Never raises: every failure becomes an error bridge whose windows render
        as ``X``, carrying a specific ``error`` code for diagnosis.
        """
        try:
            with self._session_factory() as session:
                screen = session.capture_usage_screen()
            parsed = self._parser.parse(screen)
        except UsageError as err:
            logger.warning("Usage collection failed: %s (%s)", err.code, err)
            return error_bridge(err.code)
        except Exception:
            logger.exception("Usage collection crashed")
            return error_bridge("collector_crashed")

        return self._to_bridge(parsed, now)

    @staticmethod
    def _to_bridge(parsed, now):
        """Map a :class:`ParsedUsage` onto the wire contract render.py consumes."""

        def window(pct, reset):
            return {
                "utilization": pct,
                "resets_at": reset.to_iso(now) if reset is not None else None,
            }

        model_week = None
        if parsed.model_week_pct is not None:
            model_week = window(parsed.model_week_pct, parsed.model_week_reset)
            model_week["label"] = parsed.model_week_label

        return {
            "status": "ok",
            "five_hour": window(parsed.session_pct, parsed.session_reset),
            "seven_day": window(parsed.week_pct, parsed.week_reset),
            "model_week": model_week,
            "timestamp": int(time.time()),
        }
