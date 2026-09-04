"""Unit tests for the headless-CLI usage collector.

The parser is pure (str -> ParsedUsage), so every parsing and reset-resolution
test here runs offline: no tmux server, no ``claude`` binary, no network. Only
the lifecycle tests touch subprocess, and those are mocked.
"""

import os
import sys
import unittest
from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tmux_status_server.cli_usage import (  # noqa: E402
    CliUsageCollector,
    HeadlessClaudeSession,
    ParsedUsage,
    ResetSpec,
    UsageError,
    UsageScreenParser,
    _AUTH_OVERRIDE_VARS,
    _is_safe_cwd,
    default_usage_cwd,
    search_path,
    error_bridge,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def fixture(name):
    """Read a captured usage-screen fixture by file name."""
    with open(os.path.join(FIXTURES, name)) as f:
        return f.read()


LA = ZoneInfo("America/Los_Angeles")


class TestParseNominal(unittest.TestCase):
    """The real captured screen parses into the expected windows."""

    def setUp(self):
        self.parsed = UsageScreenParser().parse(fixture("usage_nominal.txt"))

    def test_session_percentage(self):
        self.assertEqual(self.parsed.session_pct, 16.0)

    def test_week_percentage(self):
        self.assertEqual(self.parsed.week_pct, 4.0)

    def test_model_week_percentage_and_label(self):
        self.assertEqual(self.parsed.model_week_pct, 0.0)

    def test_current_cli_capture_parses(self):
        """The current 2.1.260 layout preserves all three window values."""
        parsed = UsageScreenParser().parse(fixture("usage_nominal_2_1_260.txt"))
        self.assertEqual(parsed.session_pct, 4.0)
        self.assertEqual(parsed.week_pct, 1.0)
        self.assertEqual(parsed.model_week_pct, 0.0)
        self.assertEqual(self.parsed.model_week_label, "Fable")

    def test_session_reset_is_time_only(self):
        spec = self.parsed.session_reset
        self.assertEqual((spec.hour, spec.minute), (15, 50))
        self.assertEqual(spec.tzname, "America/Los_Angeles")
        self.assertIsNone(spec.month)

    def test_week_reset_carries_explicit_date(self):
        spec = self.parsed.week_reset
        self.assertEqual((spec.month, spec.day), (9, 3))
        self.assertEqual((spec.hour, spec.minute), (9, 0))

    def test_promo_banner_is_not_mistaken_for_a_window(self):
        # "+50% weekly limits promo through Sep 13" sits between sections.
        self.assertEqual(self.parsed.week_pct, 4.0)

    def test_duplicated_percentage_parsed_once(self):
        # The screen renders "16% 16% used"; the value is 16, not 1616.
        self.assertEqual(self.parsed.session_pct, 16.0)


class TestParseVariants(unittest.TestCase):
    """Layout variations that must degrade gracefully rather than mis-parse."""

    def setUp(self):
        self.parser = UsageScreenParser()

    def test_missing_model_week_section(self):
        p = self.parser.parse(fixture("usage_no_model_week.txt"))
        self.assertEqual(p.session_pct, 7.0)
        self.assertEqual(p.week_pct, 23.0)
        self.assertIsNone(p.model_week_pct)
        self.assertIsNone(p.model_week_label)

    def test_alternate_timezone(self):
        p = self.parser.parse(fixture("usage_no_model_week.txt"))
        self.assertEqual(p.session_reset.tzname, "America/New_York")
        self.assertEqual((p.session_reset.hour, p.session_reset.minute), (11, 5))

    def test_exhausted_windows_and_absent_reset_line(self):
        p = self.parser.parse(fixture("usage_full_no_reset.txt"))
        self.assertEqual(p.session_pct, 100.0)
        self.assertEqual(p.week_pct, 100.0)
        # Window full: percentage still parses, reset is simply absent.
        self.assertIsNone(p.week_reset)
        self.assertIsNotNone(p.session_reset)

    def test_distractor_percentages_are_not_windows(self):
        with self.assertRaises(UsageError) as ctx:
            self.parser.parse(fixture("usage_distractors_only.txt"))
        self.assertEqual(ctx.exception.code, "usage_parse_failed")

    def test_truncated_capture_fails_loudly(self):
        # Session parsed but week never rendered: must fail, never half-populate.
        with self.assertRaises(UsageError) as ctx:
            self.parser.parse(fixture("usage_truncated.txt"))
        self.assertEqual(ctx.exception.code, "usage_parse_failed")

    def test_login_prompt_detected(self):
        with self.assertRaises(UsageError) as ctx:
            self.parser.parse(fixture("usage_login_prompt.txt"))
        self.assertEqual(ctx.exception.code, "cli_not_authenticated")

    def test_empty_screen(self):
        with self.assertRaises(UsageError):
            self.parser.parse("")

    def test_section_order_swapped(self):
        text = (
            "Current week (all models)\n"
            "4% 4% used\n"
            "Resets Sep 3 at 9am (America/Los_Angeles)\n"
            "Current session\n"
            "16% 16% used\n"
            "Resets 3:50pm (America/Los_Angeles)\n"
        )
        p = self.parser.parse(text)
        self.assertEqual(p.session_pct, 16.0)
        self.assertEqual(p.week_pct, 4.0)

    def test_ansi_escapes_are_stripped(self):
        text = (
            "\x1b[1mCurrent session\x1b[0m\n"
            "\x1b[32m16% 16% used\x1b[0m\n"
            "Resets 3:50pm (America/Los_Angeles)\n"
            "Current week (all models)\n"
            "4% 4% used\n"
        )
        p = self.parser.parse(text)
        self.assertEqual(p.session_pct, 16.0)
        self.assertEqual(p.week_pct, 4.0)

    def test_zero_percent(self):
        text = (
            "Current session\n0% 0% used\n"
            "Current week (all models)\n0% 0% used\n"
        )
        p = self.parser.parse(text)
        self.assertEqual(p.session_pct, 0.0)
        self.assertEqual(p.week_pct, 0.0)

    def test_percentage_above_100_is_rejected(self):
        text = (
            "Current session\n1616% used\n"
            "Current week (all models)\n4% 4% used\n"
        )
        with self.assertRaises(UsageError):
            self.parser.parse(text)


class TestResetResolution(unittest.TestCase):
    """ResetSpec -> ISO 8601, which is what render.py's fmt_reset() consumes."""

    def test_time_only_resolves_to_later_today(self):
        spec = ResetSpec(raw="3:50pm", tzname="America/Los_Angeles", hour=15, minute=50)
        now = datetime(2026, 9, 1, 9, 30, tzinfo=LA)
        self.assertEqual(spec.to_iso(now), "2026-09-01T15:50:00-07:00")

    def test_time_only_already_past_rolls_to_tomorrow(self):
        spec = ResetSpec(raw="3:50pm", tzname="America/Los_Angeles", hour=15, minute=50)
        now = datetime(2026, 9, 1, 16, 30, tzinfo=LA)
        self.assertEqual(spec.to_iso(now), "2026-09-02T15:50:00-07:00")

    def test_explicit_date_uses_current_year(self):
        spec = ResetSpec(
            raw="Sep 3 at 9am", tzname="America/Los_Angeles",
            hour=9, minute=0, month=9, day=3,
        )
        now = datetime(2026, 9, 1, 9, 30, tzinfo=LA)
        self.assertEqual(spec.to_iso(now), "2026-09-03T09:00:00-07:00")

    def test_explicit_date_rolls_over_year_end(self):
        spec = ResetSpec(
            raw="Jan 2 at 9am", tzname="America/Los_Angeles",
            hour=9, minute=0, month=1, day=2,
        )
        now = datetime(2026, 12, 31, 22, 0, tzinfo=LA)
        self.assertEqual(spec.to_iso(now), "2027-01-02T09:00:00-08:00")

    def test_result_is_parseable_by_renderer(self):
        # render.py:970 fmt_reset() calls datetime.fromisoformat() on this.
        spec = ResetSpec(raw="3:50pm", tzname="America/Los_Angeles", hour=15, minute=50)
        iso = spec.to_iso(datetime(2026, 9, 1, 9, 30, tzinfo=LA))
        self.assertIsNotNone(datetime.fromisoformat(iso).tzinfo)

    def test_unknown_timezone_falls_back_to_utc(self):
        spec = ResetSpec(raw="9am", tzname="Mars/Olympus", hour=9, minute=0)
        iso = spec.to_iso(datetime(2026, 9, 1, 8, 0, tzinfo=ZoneInfo("UTC")))
        self.assertTrue(iso.endswith("+00:00"))

    def test_dst_spring_forward_gap_still_yields_valid_iso(self):
        # 2:30am on 2026-03-08 does not exist in America/Los_Angeles.
        spec = ResetSpec(raw="2:30am", tzname="America/Los_Angeles", hour=2, minute=30)
        now = datetime(2026, 3, 8, 1, 0, tzinfo=LA)
        iso = spec.to_iso(now)
        self.assertIsNotNone(datetime.fromisoformat(iso))


class TestErrorBridge(unittest.TestCase):
    """Error bridges must render as X without breaking render.py."""

    def test_shape(self):
        b = error_bridge("cli_boot_timeout")
        self.assertEqual(b["status"], "error")
        self.assertEqual(b["error"], "cli_boot_timeout")
        self.assertEqual(b["five_hour"]["utilization"], "X")
        self.assertEqual(b["seven_day"]["utilization"], "X")
        self.assertIsNone(b["five_hour"]["resets_at"])
        self.assertIsInstance(b["timestamp"], int)

    def test_status_is_error_not_the_code(self):
        # The old scraper put the code in `status`, so render.py's
        # `elif quota_status == "error"` branch was unreachable.
        self.assertEqual(error_bridge("blocked")["status"], "error")


class TestCollector(unittest.TestCase):
    """Collector maps parsed screens onto the bridge contract."""

    def _collector(self, screen=None, exc=None):
        session = mock.MagicMock()
        ctx = mock.MagicMock()
        ctx.__enter__.return_value = session
        ctx.__exit__.return_value = False
        if exc is not None:
            session.capture_usage_screen.side_effect = exc
        else:
            session.capture_usage_screen.return_value = screen
        return CliUsageCollector(session_factory=lambda: ctx), ctx

    def test_successful_collect_maps_windows(self):
        collector, _ = self._collector(fixture("usage_nominal.txt"))
        now = datetime(2026, 9, 1, 9, 30, tzinfo=LA)
        bridge = collector.collect(now=now)
        self.assertEqual(bridge["status"], "ok")
        self.assertEqual(bridge["five_hour"]["utilization"], 16.0)
        self.assertEqual(bridge["seven_day"]["utilization"], 4.0)
        self.assertEqual(bridge["five_hour"]["resets_at"], "2026-09-01T15:50:00-07:00")

    def test_model_week_stored_but_separate(self):
        collector, _ = self._collector(fixture("usage_nominal.txt"))
        bridge = collector.collect(now=datetime(2026, 9, 1, 9, 30, tzinfo=LA))
        self.assertEqual(bridge["model_week"]["utilization"], 0.0)
        self.assertEqual(bridge["model_week"]["label"], "Fable")

    def test_model_week_null_when_absent(self):
        collector, _ = self._collector(fixture("usage_no_model_week.txt"))
        bridge = collector.collect(now=datetime(2026, 9, 1, 9, 30, tzinfo=LA))
        self.assertIsNone(bridge["model_week"])

    def test_parse_failure_becomes_error_bridge(self):
        collector, _ = self._collector(fixture("usage_truncated.txt"))
        bridge = collector.collect()
        self.assertEqual(bridge["status"], "error")
        self.assertEqual(bridge["error"], "usage_parse_failed")

    def test_usage_error_from_session_is_propagated_as_code(self):
        collector, _ = self._collector(exc=UsageError("cli_boot_timeout"))
        self.assertEqual(collector.collect()["error"], "cli_boot_timeout")

    def test_unexpected_exception_is_contained(self):
        collector, _ = self._collector(exc=RuntimeError("boom"))
        bridge = collector.collect()
        self.assertEqual(bridge["status"], "error")
        self.assertEqual(bridge["error"], "collector_crashed")

    def test_session_context_manager_always_exits(self):
        collector, ctx = self._collector(exc=UsageError("usage_screen_timeout"))
        collector.collect()
        ctx.__exit__.assert_called_once()


class TestHeadlessSessionLifecycle(unittest.TestCase):
    """The tmux server must be killed on every exit path."""

    def test_kill_server_runs_on_exception(self):
        with mock.patch.object(HeadlessClaudeSession, "_tmux") as tmux, \
                mock.patch("shutil.which", return_value="/usr/bin/stub"):
            tmux.return_value.returncode = 0
            session = HeadlessClaudeSession(socket_name="test-sock")
            try:
                with session:
                    raise RuntimeError("boom")
            except RuntimeError:
                pass
            subcommands = [c.args[0] for c in tmux.call_args_list if c.args]
            # Once to clear a crashed survivor on entry, once to tear down on exit.
            self.assertEqual(subcommands.count("kill-server"), 2)
            self.assertEqual(subcommands[-1], "kill-server")

    def test_missing_claude_binary_raises_cli_not_found(self):
        with mock.patch("shutil.which", return_value=None):
            with self.assertRaises(UsageError) as ctx:
                HeadlessClaudeSession(socket_name="test-sock").__enter__()
            self.assertIn(ctx.exception.code, ("cli_not_found", "tmux_unavailable"))

    def test_uses_dedicated_socket_never_default_server(self):
        # Invariant: capture must never touch the user's default tmux server.
        session = HeadlessClaudeSession()
        self.assertTrue(session.socket_name)
        self.assertNotEqual(session.socket_name, "default")

    def test_banner_alone_is_not_readiness(self):
        # Regression: the startup banner paints ~3s before the input box is
        # live. Keying readiness off it sent /usage into a pty that dropped it,
        # producing an intermittent usage_screen_timeout.
        banner_only = (
            "[Screen Reader Mode: on via flag]\n"
            "Claude Code v2.1.257\n"
            "Opus 5 (1M context) with high effort · Claude Max\n"
            "/Volumes/Code/project\n"
        )
        self.assertFalse(HeadlessClaudeSession.is_ready(banner_only))

    def test_input_footer_is_readiness(self):
        ready = banner = "plan mode on (shift+tab to cycle)\n"
        self.assertTrue(HeadlessClaudeSession.is_ready(ready))
        self.assertTrue(HeadlessClaudeSession.is_ready(banner))

    def test_transient_effort_hint_is_not_used_for_readiness(self):
        # "effort: high · /effort" clears after ~10s, so it cannot gate readiness.
        self.assertFalse(HeadlessClaudeSession.is_ready("effort: high · /effort\n"))

    def test_booted_but_unauthenticated_is_named_not_timed_out(self):
        # The TUI can boot fully and still be logged out, showing this in the
        # footer. Waiting out the screen timeout would report the wrong cause.
        screen = (
            "Claude Code v2.1.258\n"
            "Opus 5 (1M context) with high effort · API Usage Billing\n"
            "plan mode on (shift+tab to cycle)\n"
            "Not logged in · Run /login\n"
        )
        self.assertTrue(HeadlessClaudeSession.is_ready(screen))
        with self.assertRaises(UsageError) as ctx:
            HeadlessClaudeSession._raise_if_blocked(screen)
        self.assertEqual(ctx.exception.code, "cli_not_authenticated")

    def test_authenticated_screen_passes_through(self):
        screen = (
            "Opus 5 (1M context) with high effort · Claude Max\n"
            "plan mode on (shift+tab to cycle)\n"
        )
        HeadlessClaudeSession._raise_if_blocked(screen)  # must not raise

    def test_workspace_trust_prompt_is_named_not_timed_out(self):
        # Regression: launchd runs the daemon with cwd=/, which the CLI treats
        # as untrusted. It shows this prompt, never reaches ready, and the
        # collector reported an opaque cli_boot_timeout after 45s.
        screen = (
            "[Screen Reader Mode: on via flag]\n"
            "Permission Required: Accessing workspace:\n"
            "/\n"
            "Quick safety check: Is this a project you created or one you trust?\n"
            "y. Yes, I trust this folder\n"
            "n. No, exit\n"
            "Enter y/n:\n"
        )
        with self.assertRaises(UsageError) as ctx:
            HeadlessClaudeSession._raise_if_blocked(screen)
        self.assertEqual(ctx.exception.code, "cli_workspace_untrusted")

    def test_trust_prompt_is_never_auto_answered(self):
        # Trusting a directory is the user's security decision, not ours.
        path = os.path.join(
            os.path.dirname(__file__), "..", "tmux_status_server", "cli_usage.py"
        )
        with open(path) as f:
            source = f.read()
        self.assertNotIn('send-keys", "-t", "0", "y"', source)

    def test_usage_view_detection(self):
        self.assertTrue(
            HeadlessClaudeSession.shows_usage("Current week (all models)\n4% used\n")
        )
        self.assertFalse(HeadlessClaudeSession.shows_usage("Current session\n"))

    def test_open_usage_view_without_limit_windows_is_detected(self):
        """The live API-account screen is open but has no subscription limits."""
        screen = fixture("usage_api_account_no_windows.txt")
        self.assertTrue(HeadlessClaudeSession.shows_usage_view(screen))
        self.assertFalse(HeadlessClaudeSession.shows_usage(screen))

    def test_open_usage_view_without_windows_gets_specific_error(self):
        """An opened dialog cannot collapse into usage_screen_timeout."""
        session = HeadlessClaudeSession()
        screen = fixture("usage_api_account_no_windows.txt")
        with mock.patch.object(session, "_capture", return_value=screen), \
                mock.patch("time.monotonic", side_effect=(0.0, 0.0, 2.0)), \
                mock.patch("time.sleep"):
            with self.assertRaises(UsageError) as ctx:
                session._wait_for(session.shows_usage, 1.0, "usage_screen_timeout")
        self.assertEqual(ctx.exception.code, "usage_no_limit_windows")

    def test_closed_usage_view_retains_screen_timeout(self):
        """A dropped /usage command remains distinguishable from absent limits."""
        session = HeadlessClaudeSession()
        screen = "plan mode on (shift+tab to cycle)\n"
        with mock.patch.object(session, "_capture", return_value=screen), \
                mock.patch("time.monotonic", side_effect=(0.0, 0.0, 2.0)), \
                mock.patch("time.sleep"):
            with self.assertRaises(UsageError) as ctx:
                session._wait_for(session.shows_usage, 1.0, "usage_screen_timeout")
        self.assertEqual(ctx.exception.code, "usage_screen_timeout")

    def test_timeout_warning_reports_markers_without_full_screen(self):
        """INFO-level daemons get diagnosis without dumping the whole pane."""
        session = HeadlessClaudeSession()
        screen = fixture("usage_api_account_no_windows.txt")
        with mock.patch.object(session, "_capture", return_value=screen), \
                mock.patch("time.monotonic", side_effect=(0.0, 0.0, 2.0)), \
                mock.patch("time.sleep"), \
                self.assertLogs("tmux_status_server.cli_usage", level="WARNING") as logs:
            with self.assertRaises(UsageError):
                session._wait_for(session.shows_usage, 1.0, "usage_screen_timeout")
        warning = "\n".join(logs.output)
        self.assertIn("usage_dialog=yes", warning)
        self.assertIn("session_heading=no", warning)
        self.assertIn("week_heading=no", warning)
        self.assertNotIn("Plugin skill-listing footprint", warning)

    def test_retry_boundary_does_not_emit_terminal_warning(self):
        """The halfway retry is not reported as a completed collection failure."""
        session = HeadlessClaudeSession()
        screen = fixture("usage_api_account_no_windows.txt")
        with mock.patch.object(session, "_capture", return_value=screen), \
                mock.patch("time.monotonic", side_effect=(0.0, 0.0, 2.0)), \
                mock.patch("time.sleep"), \
                mock.patch("tmux_status_server.cli_usage.logger.warning") as warning:
            with self.assertRaises(UsageError):
                session._wait_for(
                    session.shows_usage,
                    1.0,
                    "usage_screen_timeout",
                    warn_on_timeout=False,
                )
        warning.assert_not_called()

    def test_fixed_capture_geometry(self):
        # Wrapping width is contractual: fixtures only match at 120x45.
        session = HeadlessClaudeSession()
        self.assertEqual((session.width, session.height), (120, 45))

    def test_capture_scrubs_every_documented_auth_override(self):
        """The pane shell cannot reintroduce an alternate account selector."""
        claude = "/Applications/Claude Code/bin/claude cli"

        def which(name, path=None):
            return "/opt/homebrew/bin/tmux" if name == "tmux" else claude

        with mock.patch("shutil.which", side_effect=which), \
                mock.patch.object(HeadlessClaudeSession, "_tmux") as tmux:
            tmux.return_value.returncode = 0
            with HeadlessClaudeSession(socket_name="test-sock"):
                pass

        new_session = next(
            call for call in tmux.call_args_list if call.args[0] == "new-session"
        )
        command = new_session.args[-1]
        expected_prefix = "/usr/bin/env " + " ".join(
            f"-u {name}" for name in _AUTH_OVERRIDE_VARS
        )
        self.assertTrue(command.startswith(expected_prefix + " "))
        self.assertIn("'/Applications/Claude Code/bin/claude cli'", command)
        self.assertTrue(command.endswith(" --ax-screen-reader --permission-mode plan"))

    def test_capture_can_explicitly_inherit_auth_environment(self):
        """The opt-out omits env scrubbing but still quotes the binary path."""
        with mock.patch("shutil.which", return_value="/path with spaces/claude"), \
                mock.patch.object(HeadlessClaudeSession, "_tmux") as tmux:
            tmux.return_value.returncode = 0
            with HeadlessClaudeSession(
                socket_name="test-sock", inherit_auth_env=True
            ):
                pass

        new_session = next(
            call for call in tmux.call_args_list if call.args[0] == "new-session"
        )
        self.assertEqual(
            new_session.args[-1],
            "'/path with spaces/claude' --ax-screen-reader --permission-mode plan",
        )

    def test_capture_preserves_credential_store_and_network_routing(self):
        """Isolation does not redirect the user's login store or endpoint."""
        self.assertNotIn("CLAUDE_CONFIG_DIR", _AUTH_OVERRIDE_VARS)
        self.assertNotIn("ANTHROPIC_BASE_URL", _AUTH_OVERRIDE_VARS)


class TestBinaryResolutionUnderMinimalPath(unittest.TestCase):
    """Regression: the daemon runs under launchd/systemd with a minimal PATH.

    launchd does not export /opt/homebrew/bin (tmux) or ~/.local/bin (claude),
    so resolving either against the inherited PATH alone returns None and every
    collection fails with tmux_unavailable. render.py:54 already solves this
    with _EXTRA_PATH; the collector must do the same.
    """

    LAUNCHD_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"

    def test_search_path_adds_homebrew(self):
        with mock.patch.dict(os.environ, {"PATH": self.LAUNCHD_PATH}, clear=False):
            self.assertIn("/opt/homebrew/bin", search_path().split(os.pathsep))

    def test_search_path_adds_user_local_bin(self):
        # `claude` installs to ~/.local/bin, which render.py's list omits.
        with mock.patch.dict(os.environ, {"PATH": self.LAUNCHD_PATH}, clear=False):
            self.assertIn(
                os.path.expanduser("~/.local/bin"), search_path().split(os.pathsep)
            )

    def test_search_path_preserves_and_does_not_duplicate_existing(self):
        with mock.patch.dict(os.environ, {"PATH": "/opt/homebrew/bin:/usr/bin"}):
            parts = search_path().split(os.pathsep)
            self.assertIn("/usr/bin", parts)
            self.assertEqual(parts.count("/opt/homebrew/bin"), 1)

    def test_which_is_queried_with_the_augmented_path(self):
        # The bug was calling shutil.which() with no path= argument.
        with mock.patch("shutil.which", return_value="/stub/bin/x") as which, \
                mock.patch.object(HeadlessClaudeSession, "_tmux") as tmux:
            tmux.return_value.returncode = 0
            with HeadlessClaudeSession(socket_name="test-sock"):
                pass
            for call in which.call_args_list:
                self.assertIn(
                    "path", call.kwargs,
                    f"shutil.which({call.args[0]!r}) ignored the augmented PATH",
                )
                self.assertIn("/opt/homebrew/bin", call.kwargs["path"])

    def test_subprocess_env_carries_the_augmented_path(self):
        # tmux spawns the CLI through a shell, which needs to resolve it too.
        with mock.patch("shutil.which", return_value="/stub/bin/x"), \
                mock.patch("subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = ""
            with HeadlessClaudeSession(socket_name="test-sock"):
                pass
            self.assertTrue(run.call_args_list, "no subprocess calls made")
            for call in run.call_args_list:
                env = call.kwargs.get("env")
                self.assertIsNotNone(env, "tmux invoked without an explicit env")
                self.assertIn("/opt/homebrew/bin", env["PATH"])

    def test_resolved_binaries_are_absolute(self):
        with mock.patch("shutil.which", return_value="/opt/homebrew/bin/tmux"), \
                mock.patch.object(HeadlessClaudeSession, "_tmux") as tmux:
            tmux.return_value.returncode = 0
            with HeadlessClaudeSession(socket_name="test-sock") as s:
                self.assertTrue(os.path.isabs(s.tmux_bin))
                self.assertTrue(os.path.isabs(s.claude_bin))


class TestDefaultUsageCwd(unittest.TestCase):
    """The capture must start in a directory the CLI will not prompt about."""

    def _config(self, payload):
        import tempfile, json as _json
        d = tempfile.mkdtemp()
        path = os.path.join(d, ".claude.json")
        with open(path, "w") as f:
            _json.dump(payload, f)
        return path

    def test_prefers_a_trusted_directory(self):
        cfg = self._config({"projects": {
            "/nonexistent/gone": {"hasTrustDialogAccepted": True},
            os.getcwd(): {"hasTrustDialogAccepted": True},
        }})
        self.assertEqual(default_usage_cwd(config_path=cfg), os.getcwd())

    def test_ignores_untrusted_entries(self):
        cfg = self._config({"projects": {
            os.getcwd(): {"hasTrustDialogAccepted": False},
        }})
        # No trusted candidate -> HOME, even though HOME may itself prompt;
        # the trust prompt is then detected and named rather than timing out.
        self.assertEqual(default_usage_cwd(config_path=cfg),
                         os.path.expanduser("~"))

    def test_ignores_directories_that_no_longer_exist(self):
        cfg = self._config({"projects": {
            "/nonexistent/gone": {"hasTrustDialogAccepted": True},
        }})
        self.assertEqual(default_usage_cwd(config_path=cfg),
                         os.path.expanduser("~"))

    def test_missing_config_falls_back_to_home(self):
        self.assertEqual(default_usage_cwd(config_path="/nonexistent/.claude.json"),
                         os.path.expanduser("~"))

    def test_malformed_config_falls_back_to_home(self):
        import tempfile
        d = tempfile.mkdtemp()
        path = os.path.join(d, ".claude.json")
        with open(path, "w") as f:
            f.write("{not json")
        self.assertEqual(default_usage_cwd(config_path=path),
                         os.path.expanduser("~"))

    def test_selection_is_deterministic(self):
        cfg = self._config({"projects": {
            os.getcwd(): {"hasTrustDialogAccepted": True},
            os.path.dirname(os.getcwd()): {"hasTrustDialogAccepted": True},
        }})
        self.assertEqual(default_usage_cwd(config_path=cfg),
                         default_usage_cwd(config_path=cfg))

    def test_world_writable_directory_is_rejected(self):
        # The CLI reads CLAUDE.md and settings from its cwd, so a world-writable
        # one lets any local process inject instructions into the capture.
        import tempfile, stat as _stat
        d = tempfile.mkdtemp()
        os.chmod(d, 0o777)
        self.assertFalse(_is_safe_cwd(d))
        cfg = self._config({"projects": {d: {"hasTrustDialogAccepted": True}}})
        self.assertNotEqual(default_usage_cwd(config_path=cfg), d)

    def test_user_owned_private_directory_is_accepted(self):
        import tempfile
        d = tempfile.mkdtemp()
        os.chmod(d, 0o755)
        self.assertTrue(_is_safe_cwd(d))

    def test_nonexistent_path_is_rejected(self):
        self.assertFalse(_is_safe_cwd("/nonexistent/nope"))

    def test_file_is_not_a_valid_cwd(self):
        import tempfile
        fd, path = tempfile.mkstemp()
        os.close(fd)
        self.assertFalse(_is_safe_cwd(path))

    def test_session_uses_the_default_when_no_cwd_given(self):
        session = HeadlessClaudeSession()
        self.assertTrue(session.cwd, "capture must not inherit launchd's cwd (/)")
        self.assertNotEqual(str(session.cwd), "/")


class TestReap(unittest.TestCase):
    """kill-server returns before the pane child necessarily exits."""

    def test_no_pid_is_a_noop(self):
        with mock.patch("os.kill") as kill:
            HeadlessClaudeSession._reap(None)
            kill.assert_not_called()

    def test_returns_as_soon_as_process_is_gone(self):
        with mock.patch("os.kill", side_effect=ProcessLookupError) as kill:
            HeadlessClaudeSession._reap(4242, timeout=5.0)
            # Only the liveness probe; no SIGKILL needed.
            kill.assert_called_once_with(4242, 0)

    def test_escalates_to_sigkill_when_process_survives(self):
        import signal as _signal
        with mock.patch("os.kill") as kill, mock.patch("time.sleep"):
            HeadlessClaudeSession._reap(4242, timeout=0.01)
            self.assertIn(mock.call(4242, _signal.SIGKILL), kill.call_args_list)

    def test_sigkill_race_is_tolerated(self):
        # Process may exit between the final probe and the SIGKILL.
        with mock.patch("os.kill", side_effect=ProcessLookupError):
            HeadlessClaudeSession._reap(4242, timeout=0.0)  # must not raise


if __name__ == "__main__":
    unittest.main()
