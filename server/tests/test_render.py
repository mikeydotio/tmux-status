"""Tests for the render daemon (tmux_status_server.render).

These exercise the pure logic the daemon uses to precompute per-pane status:
the in-memory process-tree walk, session/transcript resolution, transcript
parsing, quota/cost computation, the byte-exact shell env-line contract, the
git-line port, and the cache writer/pruner. Network and tmux are never touched
(quota fetch is disabled via an empty source; tmux/ps are monkeypatched).
"""

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tmux_status_server import render  # noqa: E402

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def _append_json(path, record):
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")


# ── Process map / ancestor walk ────────────────────────────────────────────
class TestParsePsOutput(unittest.TestCase):
    def test_parses_pid_ppid(self):
        m = render._parse_ps_output("  100 1\n  200 100\n  300 200\n")
        self.assertEqual(m, {100: 1, 200: 100, 300: 200})

    def test_skips_garbage_lines(self):
        m = render._parse_ps_output("100 1\nnot a row\n\n200 abc\n300 200\n")
        self.assertEqual(m, {100: 1, 300: 200})

    def test_empty_input(self):
        self.assertEqual(render._parse_ps_output(""), {})


class TestProcessSnapshot(unittest.TestCase):
    def test_parses_parent_start_and_command(self):
        text = (
            "  100 1 Tue Aug 18 20:00:00 2026 /bin/zsh\n"
            "  200 100 Tue Aug 18 20:01:02 2026 /opt/homebrew/bin/codex\n"
        )
        processes = render._parse_process_output(text)
        self.assertEqual(processes[200]["ppid"], 100)
        self.assertEqual(processes[200]["command"], "/opt/homebrew/bin/codex")
        self.assertGreater(processes[200]["started_at"], processes[100]["started_at"])

    def test_skips_malformed_rows(self):
        self.assertEqual(render._parse_process_output("not a process row\n"), {})


class TestWalkToAncestor(unittest.TestCase):
    def setUp(self):
        self.m = {300: 200, 200: 100, 100: 1}

    def test_direct_self_match(self):
        self.assertTrue(render.walk_to_ancestor(300, 300, self.m))

    def test_deep_chain_match(self):
        self.assertTrue(render.walk_to_ancestor(300, 100, self.m))

    def test_not_a_descendant(self):
        self.assertFalse(render.walk_to_ancestor(300, 999, self.m))

    def test_stops_at_pid_1(self):
        # 1 is never a match target (excluded before comparison)
        self.assertFalse(render.walk_to_ancestor(300, 1, self.m))

    def test_off_the_map_returns_false(self):
        self.assertFalse(render.walk_to_ancestor(555, 100, self.m))

    def test_self_cycle_guard(self):
        self.assertFalse(render.walk_to_ancestor(5, 999, {5: 5}))

    def test_two_node_cycle_guard(self):
        self.assertFalse(render.walk_to_ancestor(5, 999, {5: 6, 6: 5}))

    def test_non_integer_inputs(self):
        self.assertFalse(render.walk_to_ancestor(None, 1, self.m))
        self.assertFalse(render.walk_to_ancestor("x", 1, self.m))


class TestAgentProcessSelection(unittest.TestCase):
    @staticmethod
    def _process(pid, ppid, command, started_at):
        return {"pid": pid, "ppid": ppid, "command": command,
                "started_at": started_at}

    def test_nearest_descendant_wins_across_providers(self):
        processes = {
            10: self._process(10, 1, "zsh", 1),
            20: self._process(20, 10, "claude", 2),
            30: self._process(30, 20, "codex", 3),
        }
        sessions = [{"pid": 20, "cwd": "/work", "session_id": "c1"}]
        selected = render.select_agent_process(10, sessions, processes)
        self.assertEqual(selected["provider"], "claude")
        self.assertEqual(selected["pid"], 20)

    def test_newest_start_breaks_equal_depth_tie(self):
        processes = {
            10: self._process(10, 1, "zsh", 1),
            20: self._process(20, 10, "claude", 2),
            30: self._process(30, 10, "/usr/local/bin/codex", 3),
        }
        sessions = [{"pid": 20, "cwd": "/work", "session_id": "c1"}]
        selected = render.select_agent_process(10, sessions, processes)
        self.assertEqual(selected["provider"], "codex")
        self.assertEqual(selected["pid"], 30)

    def test_ignores_non_agent_commands(self):
        processes = {
            10: self._process(10, 1, "zsh", 1),
            30: self._process(30, 10, "my-codex-report", 3),
        }
        self.assertIsNone(render.select_agent_process(10, [], processes))

    def test_codex_command_wins_over_stale_claude_pid_reuse(self):
        processes = {
            10: self._process(10, 1, "zsh", 1),
            30: self._process(30, 10, "codex", 3),
        }
        stale_sessions = [{"pid": 30, "cwd": "/old", "session_id": "old"}]
        selected = render.select_agent_process(10, stale_sessions, processes)
        self.assertEqual(selected["provider"], "codex")


class TestCodexRolloutResolution(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.codex_home = os.path.join(self.tmp, ".codex")
        self.sessions = os.path.join(self.codex_home, "sessions", "2026", "08", "18")
        os.makedirs(self.sessions)

    def _rollout(self, name):
        path = os.path.join(self.sessions, name)
        _write(path, "{}\n")
        return path

    def _session_rollout(self, name, thread_id, parent_id=None):
        path = os.path.join(self.sessions, name)
        payload = {"id": thread_id}
        if parent_id is not None:
            payload["parent_thread_id"] = parent_id
        _write(path, json.dumps({"type": "session_meta", "payload": payload}) + "\n")
        return path

    @staticmethod
    def _activity(path, timestamp):
        _append_json(path, {
            "timestamp": timestamp,
            "type": "event_msg",
            "payload": {"type": "task_started"},
        })

    def test_linux_resolves_one_exact_open_rollout(self):
        rollout = self._rollout("rollout-one.jsonl")
        proc_root = os.path.join(self.tmp, "proc")
        fd_dir = os.path.join(proc_root, "123", "fd")
        os.makedirs(fd_dir)
        os.symlink(rollout, os.path.join(fd_dir, "7"))
        resolved = render.resolve_codex_rollouts(
            [123], self.codex_home, system_name="Linux", proc_root=proc_root,
        )
        self.assertEqual(resolved, {123: os.path.realpath(rollout)})

    def test_linux_ambiguous_open_rollouts_fail_safe(self):
        one = self._rollout("rollout-one.jsonl")
        two = self._rollout("rollout-two.jsonl")
        proc_root = os.path.join(self.tmp, "proc")
        fd_dir = os.path.join(proc_root, "123", "fd")
        os.makedirs(fd_dir)
        os.symlink(one, os.path.join(fd_dir, "7"))
        os.symlink(two, os.path.join(fd_dir, "8"))
        resolved = render.resolve_codex_rollouts(
            [123], self.codex_home, system_name="Linux", proc_root=proc_root,
        )
        self.assertEqual(resolved, {})

    def test_linux_selects_primary_with_open_subagent_rollout(self):
        root = self._session_rollout("rollout-root.jsonl", "root")
        child = self._session_rollout("rollout-child.jsonl", "child", "root")
        proc_root = os.path.join(self.tmp, "proc")
        fd_dir = os.path.join(proc_root, "123", "fd")
        os.makedirs(fd_dir)
        os.symlink(root, os.path.join(fd_dir, "7"))
        os.symlink(child, os.path.join(fd_dir, "8"))
        resolved = render.resolve_codex_rollouts(
            [123], self.codex_home, system_name="Linux", proc_root=proc_root,
        )
        self.assertEqual(resolved, {123: os.path.realpath(root)})

    def test_multiple_rollouts_with_unproven_parent_fail_safe(self):
        root = self._session_rollout("rollout-root.jsonl", "root")
        child = self._session_rollout("rollout-child.jsonl", "child", "missing")
        output = f"p123\nn{root}\nn{child}\n"
        self.assertEqual(
            render._parse_lsof_rollouts(output, [123], self.codex_home), {}
        )

    def test_multiple_root_rollouts_fail_safe(self):
        one = self._session_rollout("rollout-one.jsonl", "one")
        two = self._session_rollout("rollout-two.jsonl", "two")
        output = f"p123\nn{one}\nn{two}\n"
        self.assertEqual(
            render._parse_lsof_rollouts(output, [123], self.codex_home), {}
        )

    def test_completed_old_root_yields_to_newer_active_root(self):
        old = self._session_rollout("rollout-old.jsonl", "old")
        new = self._session_rollout("rollout-new.jsonl", "new")
        self._activity(old, "2026-08-23T22:21:46Z")
        self._activity(new, "2026-08-23T22:22:18Z")
        decision = render._select_rollout_decision(
            [old, new], self.codex_home,
        )
        self.assertEqual(decision["state"], "selected")
        self.assertEqual(decision["path"], os.path.realpath(new))

    def test_resumed_older_root_wins_on_newer_root_event(self):
        old = self._session_rollout("rollout-old.jsonl", "old")
        new = self._session_rollout("rollout-new.jsonl", "new")
        self._activity(old, "2026-08-23T22:21:46Z")
        self._activity(new, "2026-08-23T22:22:18Z")
        first = render._select_rollout_decision([old, new], self.codex_home)
        self._activity(old, "2026-08-23T22:23:00Z")
        resumed = render._select_rollout_decision(
            [old, new], self.codex_home,
            previous={
                "rollout": first["path"],
                "thread_id": first["thread_id"],
                "activity": first["activity"],
            },
        )
        self.assertEqual(resumed["state"], "selected")
        self.assertEqual(resumed["path"], os.path.realpath(old))

    def test_child_only_activity_does_not_steal_root_selection(self):
        first = self._session_rollout("rollout-first.jsonl", "first")
        child = self._session_rollout("rollout-child.jsonl", "child", "first")
        second = self._session_rollout("rollout-second.jsonl", "second")
        self._activity(first, "2026-08-23T22:21:00Z")
        self._activity(child, "2026-08-23T23:00:00Z")
        self._activity(second, "2026-08-23T22:22:00Z")
        decision = render._select_rollout_decision(
            [first, child, second], self.codex_home,
        )
        self.assertEqual(decision["path"], os.path.realpath(second))

    def test_equal_root_activity_retains_last_known_good(self):
        one = self._session_rollout("rollout-one.jsonl", "one")
        two = self._session_rollout("rollout-two.jsonl", "two")
        self._activity(one, "2026-08-23T22:21:00Z")
        self._activity(two, "2026-08-23T22:21:00Z")
        previous = {"rollout": one, "thread_id": "one", "activity": 1}
        decision = render._select_rollout_decision(
            [one, two], self.codex_home, previous=previous,
        )
        self.assertEqual(decision["state"], "retain")
        self.assertEqual(decision["path"], os.path.realpath(one))

    def test_malformed_graph_retains_last_known_good(self):
        root = self._session_rollout("rollout-root.jsonl", "root")
        malformed = self._rollout("rollout-malformed.jsonl")
        decision = render._select_rollout_decision(
            [root, malformed], self.codex_home,
            previous={"rollout": root, "thread_id": "root", "activity": 1},
        )
        self.assertEqual(decision["state"], "retain")
        self.assertEqual(decision["path"], os.path.realpath(root))

    def test_equal_root_activity_without_previous_fails_closed(self):
        one = self._session_rollout("rollout-one.jsonl", "one")
        two = self._session_rollout("rollout-two.jsonl", "two")
        self._activity(one, "2026-08-23T22:21:00Z")
        self._activity(two, "2026-08-23T22:21:00Z")
        decision = render._select_rollout_decision([one, two], self.codex_home)
        self.assertEqual(decision["state"], "none")
        self.assertIsNone(decision["path"])

    def test_missing_selected_rollout_resets_to_exact_open_root(self):
        old = self._session_rollout("rollout-old.jsonl", "old")
        current = self._session_rollout("rollout-current.jsonl", "current")
        decision = render._select_rollout_decision(
            [current], self.codex_home,
            previous={"rollout": old, "thread_id": "old", "activity": 100},
        )
        self.assertEqual(decision["state"], "selected")
        self.assertEqual(decision["path"], os.path.realpath(current))

    def test_linux_does_not_accept_jsonl_outside_codex_sessions(self):
        outside = os.path.join(self.tmp, "other.jsonl")
        _write(outside, "{}\n")
        proc_root = os.path.join(self.tmp, "proc")
        fd_dir = os.path.join(proc_root, "123", "fd")
        os.makedirs(fd_dir)
        os.symlink(outside, os.path.join(fd_dir, "7"))
        resolved = render.resolve_codex_rollouts(
            [123], self.codex_home, system_name="Linux", proc_root=proc_root,
        )
        self.assertEqual(resolved, {})

    def test_macos_uses_one_batched_lsof_snapshot(self):
        one = self._rollout("rollout-one.jsonl")
        two = self._rollout("rollout-two.jsonl")
        output = f"p123\nn{one}\np456\nn{two}\n"
        completed = subprocess.CompletedProcess([], 0, stdout=output, stderr="")
        with mock.patch.object(render.subprocess, "run", return_value=completed) as run:
            resolved = render.resolve_codex_rollouts(
                [123, 456], self.codex_home, system_name="Darwin",
            )
        self.assertEqual(resolved, {
            123: os.path.realpath(one), 456: os.path.realpath(two),
        })
        run.assert_called_once()
        self.assertIn("123,456", run.call_args.args[0])

    def test_macos_missing_identity_fails_safe(self):
        completed = subprocess.CompletedProcess([], 1, stdout="p123\n", stderr="")
        with mock.patch.object(render.subprocess, "run", return_value=completed):
            resolved = render.resolve_codex_rollouts(
                [123], self.codex_home, system_name="Darwin",
            )
        self.assertEqual(resolved, {})


class TestCodexRolloutParsing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.rollout = os.path.join(self.tmp, "rollout.jsonl")
        self.now = 1_000_000

    @staticmethod
    def _turn(model="gpt-5.6-sol", effort="xhigh", **extra):
        payload = {"model": model, "effort": effort, **extra}
        return {"type": "turn_context", "payload": payload}

    @staticmethod
    def _started(window, **extra):
        payload = {"type": "task_started", "model_context_window": window, **extra}
        return {"type": "event_msg", "payload": payload}

    @staticmethod
    def _tokens(total, primary=None, secondary=None, reached=None,
                limit_id=None, limit_name=None, timestamp=None, **extra):
        limits = {
            "primary": primary,
            "secondary": secondary,
            "rate_limit_reached_type": reached,
        }
        if limit_id is not None:
            limits["limit_id"] = limit_id
        if limit_name is not None:
            limits["limit_name"] = limit_name
        payload = {
            "type": "token_count",
            "info": {"last_token_usage": {"total_tokens": total}},
            "rate_limits": limits,
            **extra,
        }
        record = {"type": "event_msg", "payload": payload}
        if timestamp is not None:
            record["timestamp"] = timestamp
        return record

    def _write_records(self, *records, prefix=""):
        _write(self.rollout, prefix + "\n".join(json.dumps(r) for r in records) + "\n")

    def test_extracts_latest_model_effort_context_and_two_quota_windows(self):
        primary = {"window_minutes": 300, "used_percent": 41.6,
                   "resets_at": self.now + 2400}
        secondary = {"window_minutes": 10080, "used_percent": 64.2,
                     "resets_at": self.now + 440640}
        self._write_records(
            self._turn("gpt-5.4", "medium"),
            self._started(1000),
            self._tokens(250),
            self._turn(extra_field="ignored"),
            self._started(2000, another="ignored"),
            self._tokens(1001, primary, secondary, ignored=True),
        )
        status = render.parse_codex_rollout(self.rollout, now=self.now)
        self.assertEqual(status["provider"], "codex")
        self.assertEqual(status["model"], "gpt-5.6-sol")
        self.assertEqual(status["effort"], "xhigh")
        self.assertEqual(status["context_pct"], 50)
        self.assertEqual(status["quota_status"], "ok")
        self.assertEqual(status["quota_slots"], [
            {"duration": "5h", "reset": "40m", "pct": 42},
            {"duration": "7d", "reset": "5.1d", "pct": 64},
        ])

    def test_malformed_and_truncated_lines_are_ignored(self):
        self._write_records(
            self._turn(), self._started(100), self._tokens(20),
            prefix="{truncated json\n[]\n",
        )
        status = render.parse_codex_rollout(self.rollout, now=self.now)
        self.assertEqual(status["model"], "gpt-5.6-sol")
        self.assertEqual(status["context_pct"], 20)

    def test_scan_grows_past_large_turn_body_for_latest_context_records(self):
        large_body = {"type": "noise", "payload": {"text": "x" * 600000}}
        self._write_records(
            self._turn(), self._started(100), large_body, self._tokens(20),
        )
        status = render.parse_codex_rollout(self.rollout, now=self.now)
        self.assertEqual(status["model"], "gpt-5.6-sol")
        self.assertEqual(status["effort"], "xhigh")
        self.assertEqual(status["context_pct"], 20)

    def test_general_quota_survives_newer_model_specific_zero_snapshot(self):
        general = {"window_minutes": 10080, "used_percent": 6,
                   "resets_at": self.now + 250560}
        inactive_model_limit = {"window_minutes": 10080, "used_percent": 0,
                                "resets_at": self.now + 604800}
        large_body = {"type": "noise", "payload": {"text": "x" * 600000}}
        self._write_records(
            self._turn(),
            self._started(1000),
            self._tokens(250, primary=general, limit_id="codex",
                         timestamp="2026-08-19T15:00:00Z"),
            large_body,
            self._tokens(600, primary=inactive_model_limit,
                         limit_id="codex_bengalfox",
                         limit_name="GPT-5.3-Codex-Spark",
                         timestamp="2026-08-19T16:00:00Z"),
        )

        status = render.parse_codex_rollout(self.rollout, now=self.now)

        self.assertEqual(status["context_pct"], 60)
        self.assertEqual(status["quota_slots"], [
            {"duration": "7d", "reset": "2.9d", "pct": 6},
        ])
        self.assertEqual(status["_quota_limit_id"], "codex")

    def test_latest_general_quota_is_shared_across_codex_panes(self):
        older = render._empty_agent_status("codex")
        older.update({
            "quota_slots": [{"duration": "7d", "reset": "2.9d", "pct": 5}],
            "quota_status": "ok",
            "_quota_limit_id": "codex",
            "_quota_observed_at": 100,
        })
        newer = render._empty_agent_status("codex")
        newer.update({
            "quota_slots": [{"duration": "7d", "reset": "2.8d", "pct": 6}],
            "quota_status": "ok",
            "_quota_limit_id": "codex",
            "_quota_observed_at": 200,
        })
        inactive_model_limit = render._empty_agent_status("codex")
        inactive_model_limit.update({
            "quota_slots": [{"duration": "7d", "reset": "7.0d", "pct": 0}],
            "quota_status": "ok",
            "_quota_limit_id": "codex_bengalfox",
            "_quota_observed_at": 300,
        })

        render.share_latest_codex_quota([older, inactive_model_limit, newer])

        for status in (older, inactive_model_limit, newer):
            self.assertEqual(status["quota_slots"], [
                {"duration": "7d", "reset": "2.8d", "pct": 6},
            ])

    def test_context_is_clamped_to_one_hundred(self):
        self._write_records(self._turn(), self._started(100), self._tokens(10000))
        status = render.parse_codex_rollout(self.rollout, now=self.now)
        self.assertEqual(status["context_pct"], 100)

    def test_negative_context_is_clamped_to_zero(self):
        self._write_records(self._turn(), self._started(100), self._tokens(-10))
        status = render.parse_codex_rollout(self.rollout, now=self.now)
        self.assertEqual(status["context_pct"], 0)

    def test_partial_records_omit_only_missing_metrics(self):
        incomplete = {"window_minutes": 300, "used_percent": 10}
        self._write_records(
            {"type": "turn_context", "payload": {"model": "gpt-5.6-sol"}},
            self._tokens(10, primary=incomplete),
        )
        status = render.parse_codex_rollout(self.rollout, now=self.now)
        self.assertEqual(status["model"], "gpt-5.6-sol")
        self.assertIsNone(status["effort"])
        self.assertIsNone(status["context_pct"])
        self.assertEqual(status["quota_slots"], [])

    def test_one_quota_window_and_reached_limit(self):
        primary = {"window_minutes": 300, "used_percent": 100,
                   "resets_at": self.now + 60}
        self._write_records(self._turn(), self._started(100),
                            self._tokens(50, primary=primary, reached="primary"))
        status = render.parse_codex_rollout(self.rollout, now=self.now)
        self.assertEqual(status["quota_status"], "blocked")
        self.assertEqual(status["quota_slots"], [
            {"duration": "5h", "reset": "1m", "pct": 100},
        ])

    def test_missing_file_returns_empty_codex_record(self):
        status = render.parse_codex_rollout(os.path.join(self.tmp, "missing.jsonl"))
        self.assertEqual(status["provider"], "codex")
        self.assertIsNone(status["model"])
        self.assertEqual(status["quota_slots"], [])

    def test_duration_labels(self):
        self.assertEqual(render.format_window_duration(300), "5h")
        self.assertEqual(render.format_window_duration(10080), "7d")
        self.assertEqual(render.format_window_duration(90), "90m")

# ── Session discovery ──────────────────────────────────────────────────────
class TestLoadSessions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.claude = os.path.join(self.tmp, ".claude")

    def test_loads_valid_sessions(self):
        _write(os.path.join(self.claude, "sessions", "a.json"),
               json.dumps({"pid": 111, "cwd": "/work/a"}))
        _write(os.path.join(self.claude, "sessions", "b.json"),
               json.dumps({"pid": 222, "cwd": "/work/b"}))
        sessions = render.load_sessions(self.claude)
        pids = sorted(s["pid"] for s in sessions)
        self.assertEqual(pids, [111, 222])

    def test_captures_session_id(self):
        # The live conversation id (rewritten in place on /clear) is the
        # authoritative identity the daemon keys the transcript+bridge on.
        _write(os.path.join(self.claude, "sessions", "a.json"),
               json.dumps({"pid": 111, "cwd": "/work/a", "sessionId": "sid-xyz"}))
        s = render.load_sessions(self.claude)[0]
        self.assertEqual(s["session_id"], "sid-xyz")

    def test_session_id_defaults_empty_when_absent(self):
        _write(os.path.join(self.claude, "sessions", "a.json"),
               json.dumps({"pid": 111, "cwd": "/work/a"}))
        s = render.load_sessions(self.claude)[0]
        self.assertEqual(s["session_id"], "")

    def test_skips_missing_pid(self):
        _write(os.path.join(self.claude, "sessions", "a.json"),
               json.dumps({"cwd": "/work/a"}))
        self.assertEqual(render.load_sessions(self.claude), [])

    def test_skips_unreadable(self):
        _write(os.path.join(self.claude, "sessions", "bad.json"), "{not json")
        self.assertEqual(render.load_sessions(self.claude), [])

    def test_no_sessions_dir(self):
        self.assertEqual(render.load_sessions(self.claude), [])


class TestResolvePaneSession(unittest.TestCase):
    def test_single_match(self):
        sessions = [{"pid": 200, "cwd": "/w"}]
        ps_map = {200: 150, 150: 42}
        self.assertEqual(render.resolve_pane_session(42, sessions, ps_map)["cwd"], "/w")

    def test_first_match_wins(self):
        sessions = [{"pid": 200, "cwd": "/a"}, {"pid": 300, "cwd": "/b"}]
        ps_map = {200: 42, 300: 99}
        self.assertEqual(render.resolve_pane_session(42, sessions, ps_map)["cwd"], "/a")

    def test_no_match(self):
        sessions = [{"pid": 200, "cwd": "/a"}]
        self.assertIsNone(render.resolve_pane_session(42, sessions, {200: 1}))

    def test_dead_pid_not_in_map(self):
        sessions = [{"pid": 999, "cwd": "/a"}]
        self.assertIsNone(render.resolve_pane_session(42, sessions, {}))


# ── Transcript discovery / parsing ─────────────────────────────────────────
class TestFindTranscript(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.claude = os.path.join(self.tmp, ".claude")

    def test_cwd_to_project_mapping_and_newest(self):
        proj = os.path.join(self.claude, "projects", "-work-x")
        _write(os.path.join(proj, "old.jsonl"), "{}\n")
        _write(os.path.join(proj, "new.jsonl"), "{}\n")
        os.utime(os.path.join(proj, "old.jsonl"), (1000, 1000))
        os.utime(os.path.join(proj, "new.jsonl"), (2000, 2000))
        self.assertEqual(
            os.path.basename(render.find_transcript("/work/x", self.claude)),
            "new.jsonl",
        )

    def test_rotation_picks_new_file(self):
        proj = os.path.join(self.claude, "projects", "-work-x")
        _write(os.path.join(proj, "a.jsonl"), "{}\n")
        os.utime(os.path.join(proj, "a.jsonl"), (1000, 1000))
        _write(os.path.join(proj, "b.jsonl"), "{}\n")
        os.utime(os.path.join(proj, "b.jsonl"), (3000, 3000))
        self.assertEqual(
            os.path.basename(render.find_transcript("/work/x", self.claude)), "b.jsonl")

    def test_no_project_dir(self):
        self.assertIsNone(render.find_transcript("/nope", self.claude))

    def test_no_cwd(self):
        self.assertIsNone(render.find_transcript(None, self.claude))

    def test_session_id_resolves_exact_file_not_newest(self):
        # With a known sessionId, resolve {sessionId}.jsonl exactly — never the
        # newest, which after /clear is a different (prior) session's transcript.
        proj = os.path.join(self.claude, "projects", "-work-x")
        _write(os.path.join(proj, "old.jsonl"), "{}\n")
        _write(os.path.join(proj, "sid-1.jsonl"), "{}\n")
        os.utime(os.path.join(proj, "old.jsonl"), (5000, 5000))   # newest by mtime
        os.utime(os.path.join(proj, "sid-1.jsonl"), (1000, 1000))
        self.assertEqual(
            os.path.basename(render.find_transcript("/work/x", self.claude, "sid-1")),
            "sid-1.jsonl",
        )

    def test_session_id_missing_file_returns_none(self):
        # New/cleared session whose transcript does not exist yet must return
        # None (so cost is $0), NOT fall back to a prior session's transcript.
        proj = os.path.join(self.claude, "projects", "-work-x")
        _write(os.path.join(proj, "old.jsonl"), "{}\n")
        self.assertIsNone(render.find_transcript("/work/x", self.claude, "sid-new"))


class TestParseTranscript(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tr = os.path.join(self.tmp, "t.jsonl")

    def _home_without_settings(self):
        # parse_transcript falls back to ~/.claude/settings.json for effort;
        # point HOME at an empty dir so the fallback is a no-op (effort -> auto).
        return mock.patch.dict(os.environ, {"HOME": self.tmp})

    def test_model_thinking_effort_conversation(self):
        lines = [
            json.dumps({"type": "user", "sessionId": "conv-1",
                        "message": {"content": "<local-command-stdout>Set effort level to high</local-command-stdout>"}}),
            json.dumps({"type": "assistant",
                        "message": {"model": "claude-opus-4-8",
                                    "content": [{"type": "thinking"}, {"type": "text"}]}}),
        ]
        _write(self.tr, "\n".join(lines) + "\n")
        with self._home_without_settings():
            d = render.parse_transcript(self.tr)
        self.assertEqual(d["model"], "claude-opus-4-8")
        self.assertTrue(d["has_thinking"])
        self.assertEqual(d["effort"], "high")
        self.assertEqual(d["conversation_id"], "conv-1")

    def test_effort_defaults_to_auto(self):
        _write(self.tr, json.dumps({"type": "assistant",
               "message": {"model": "claude-sonnet-4-6", "content": []}}) + "\n")
        with self._home_without_settings():
            d = render.parse_transcript(self.tr)
        self.assertEqual(d["effort"], "auto")
        self.assertFalse(d["has_thinking"])

    def test_malformed_lines_do_not_crash(self):
        _write(self.tr, "{garbage\n" + json.dumps({"type": "assistant",
               "message": {"model": "claude-opus-4-8", "content": []}}) + "\n")
        with self._home_without_settings():
            d = render.parse_transcript(self.tr)
        self.assertEqual(d["model"], "claude-opus-4-8")

    def test_missing_file(self):
        d = render.parse_transcript(os.path.join(self.tmp, "nope.jsonl"))
        self.assertEqual(d["model"], "")
        self.assertEqual(d["effort"], "auto")


class TestReadContextPct(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_reads_primary_bridge(self):
        _write(os.path.join(self.tmp, ".cache", "tmux-status", "claude-ctx-c1.json"),
               json.dumps({"used_pct": 42}))
        self.assertEqual(render.read_context_pct("c1", self.tmp), 42)

    def test_falls_back_to_legacy(self):
        _write(os.path.join(self.tmp, ".cache", "coderig", "claude-ctx-c1.json"),
               json.dumps({"used_pct": 7}))
        self.assertEqual(render.read_context_pct("c1", self.tmp), 7)

    def test_missing_returns_default(self):
        self.assertEqual(render.read_context_pct("c1", self.tmp, default=0), 0)

    def test_no_conversation_id(self):
        self.assertEqual(render.read_context_pct("", self.tmp, default=5), 5)


class TestReadBridge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_reads_used_pct_and_model(self):
        _write(os.path.join(self.tmp, ".cache", "tmux-status", "claude-ctx-c1.json"),
               json.dumps({"used_pct": 42, "model": "claude-opus-4-8"}))
        b = render.read_bridge("c1", self.tmp)
        self.assertEqual(b["used_pct"], 42)
        self.assertEqual(b["model"], "claude-opus-4-8")

    def test_legacy_dir_has_no_model(self):
        # Legacy coderig bridges predate the model key -> model "" (transcript wins).
        _write(os.path.join(self.tmp, ".cache", "coderig", "claude-ctx-c1.json"),
               json.dumps({"used_pct": 7}))
        b = render.read_bridge("c1", self.tmp)
        self.assertEqual(b["used_pct"], 7)
        self.assertEqual(b["model"], "")

    def test_empty_sid_short_circuits_to_defaults(self):
        b = render.read_bridge("", self.tmp, default=3)
        self.assertEqual(b, {"used_pct": 3, "model": "", "effort": "", "has_thinking": None})

    def test_missing_file_returns_defaults(self):
        b = render.read_bridge("c1", self.tmp)
        self.assertEqual(b, {"used_pct": 0, "model": "", "effort": "", "has_thinking": None})

    def test_reads_live_effort_and_thinking(self):
        # The statusLine hook writes the live session effort/thinking into the
        # bridge; read_bridge surfaces them so the daemon can prefer them.
        _write(os.path.join(self.tmp, ".cache", "tmux-status", "claude-ctx-c1.json"),
               json.dumps({"used_pct": 5, "model": "claude-opus-4-8",
                           "effort": "xhigh", "thinking": True}))
        b = render.read_bridge("c1", self.tmp)
        self.assertEqual(b["effort"], "xhigh")
        self.assertIs(b["has_thinking"], True)

    def test_absent_effort_thinking_are_falsy_defaults(self):
        # Older bridges predate these keys -> effort "" and has_thinking None so
        # render_once falls back to the transcript/settings-derived values.
        _write(os.path.join(self.tmp, ".cache", "tmux-status", "claude-ctx-c1.json"),
               json.dumps({"used_pct": 5, "model": "claude-opus-4-8"}))
        b = render.read_bridge("c1", self.tmp)
        self.assertEqual(b["effort"], "")
        self.assertIsNone(b["has_thinking"])


class TestCodexHomeSettings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _load(self, env_value=""):
        with mock.patch.dict(os.environ, {"CODEX_HOME": env_value}, clear=False):
            os.environ.pop("XDG_CONFIG_HOME", None)
            return render.load_settings(self.tmp)

    def test_configured_codex_home_wins_and_expands_tilde(self):
        _write(
            os.path.join(self.tmp, ".config", "tmux-status", "settings.conf"),
            "CODEX_HOME=~/custom-codex\n",
        )
        settings = self._load(os.path.join(self.tmp, "env-codex"))
        self.assertEqual(settings["codex_home"], os.path.join(self.tmp, "custom-codex"))

    def test_environment_is_fallback(self):
        env_home = os.path.join(self.tmp, "env-codex")
        self.assertEqual(self._load(env_home)["codex_home"], env_home)

    def test_default_is_dot_codex_under_home(self):
        self.assertEqual(
            self._load("")["codex_home"], os.path.join(self.tmp, ".codex"),
        )


# ── Quota ──────────────────────────────────────────────────────────────────
class TestComputeQuotaVars(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bridge = os.path.join(self.tmp, "quota.json")
        # source="" disables the network fetch so we read only the bridge file.
        self.settings = {"quota_bridge": self.bridge, "quota_source": "",
                         "quota_api_key": "", "quota_cache_ttl": 0, "quota_max_stale": 0}

    def test_ok_status_rounds_utilization(self):
        _write(self.bridge, json.dumps({"status": "ok",
               "five_hour": {"utilization": 41.6, "resets_at": ""},
               "seven_day": {"utilization": 64.2, "resets_at": ""}}))
        q = render.compute_quota_vars(self.settings, self.tmp)
        self.assertEqual(q["quota_status"], "ok")
        self.assertEqual(q["five_hour_pct"], 42)
        self.assertEqual(q["seven_day_pct"], 64)
        # ok + empty resets_at => full-window label
        self.assertEqual(q["five_hour_remain"], "5h")

    def test_error_status_is_X(self):
        _write(self.bridge, json.dumps({"status": "error",
               "five_hour": {}, "seven_day": {}}))
        q = render.compute_quota_vars(self.settings, self.tmp)
        self.assertEqual(q["five_hour_pct"], "X")
        self.assertEqual(q["five_hour_remain"], "X")

    def test_missing_bridge_is_none(self):
        q = render.compute_quota_vars(self.settings, self.tmp)
        self.assertEqual(q["quota_status"], "none")
        self.assertEqual(q["five_hour_pct"], 0)

    def test_max_stale_override(self):
        _write(self.bridge, json.dumps({"status": "ok",
               "five_hour": {"utilization": 10, "resets_at": ""},
               "seven_day": {"utilization": 10, "resets_at": ""}}))
        os.utime(self.bridge, (1000, 1000))  # very old
        self.settings["quota_max_stale"] = 1
        q = render.compute_quota_vars(self.settings, self.tmp)
        self.assertEqual(q["quota_status"], "stale")
        self.assertEqual(q["five_hour_pct"], "X")


# ── Env-line contract ──────────────────────────────────────────────────────
class TestAgentEnvLines(unittest.TestCase):
    def test_exact_normalized_claude_lines(self):
        status = {
            "provider": "claude", "model": "claude-opus-4-8", "effort": "high",
            "has_thinking": True, "context_pct": 37, "quota_status": "ok",
            "quota_warn": False,
            "quota_slots": [
                {"duration": "5h", "reset": "40m", "pct": 6},
                {"duration": "7d", "reset": "10.0h", "pct": 64},
            ],
        }
        lines = render.agent_env_lines(status)
        self.assertEqual(lines[0], "AGENT_PROVIDER=claude")
        self.assertEqual(lines[1], "AGENT_MODEL=claude-opus-4-8")
        self.assertEqual(lines[2], "AGENT_SHORT_MODEL='Opus 4.8'")
        self.assertEqual(lines[3], "AGENT_EFFORT=high")
        self.assertEqual(lines[4], "AGENT_HAS_THINKING=1")
        self.assertEqual(lines[5], "AGENT_CONTEXT_PCT=37")
        self.assertIn("AGENT_QUOTA_1_DURATION=5h", lines)
        self.assertIn("AGENT_QUOTA_2_RESET=10.0h", lines)
        self.assertFalse(any(ln.startswith("MODEL=") for ln in lines))

    def test_missing_codex_metrics_are_empty(self):
        status = render._empty_agent_status("codex")
        lines = render.agent_env_lines(status)
        self.assertIn("AGENT_MODEL=''", lines)
        self.assertIn("AGENT_EFFORT=''", lines)
        self.assertIn("AGENT_CONTEXT_PCT=''", lines)
        self.assertIn("AGENT_QUOTA_1_DURATION=''", lines)


# ── Git line ───────────────────────────────────────────────────────────────
class TestComputeGitLine(unittest.TestCase):
    def test_non_repo_returns_rel(self):
        self.assertEqual(render.compute_git_line("/var/empty", "/home/u"), "/var/empty")

    def test_home_backslash_tilde_quirk(self):
        # Reproduces the original bash `${dir/$HOME/\~}` literal backslash.
        self.assertEqual(render.compute_git_line("/home/u/proj", "/home/u"), "\\~/proj")

    def test_empty_path(self):
        self.assertEqual(render.compute_git_line("", "/home/u"), "")


# ── Cache writing / pruning / render_once ──────────────────────────────────
class TestCacheAndRenderOnce(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.render_dir = os.path.join(self.tmp, ".cache", "tmux-status", "render")
        os.makedirs(self.render_dir, exist_ok=True)

    def test_atomic_write_no_partial(self):
        path = os.path.join(self.render_dir, "pane-1.env")
        render._atomic_write(path, "MODEL=x\n", 4242)
        with open(path) as f:
            self.assertEqual(f.read(), "MODEL=x\n")
        # no leftover temp files
        self.assertEqual([n for n in os.listdir(self.render_dir) if n.endswith(".tmp")], [])

    def test_prune_removes_dead_panes(self):
        _write(os.path.join(self.render_dir, "pane-100.env"), "GIT_LINE=x\n")
        _write(os.path.join(self.render_dir, "pane-200.env"), "GIT_LINE=y\n")
        _write(os.path.join(self.render_dir, "pane-200.codex.json"), "{}\n")
        render._prune(self.render_dir, {100})
        names = set(os.listdir(self.render_dir))
        self.assertIn("pane-100.env", names)
        self.assertNotIn("pane-200.env", names)
        self.assertNotIn("pane-200.codex.json", names)

    def test_render_once_no_tmux_returns_zero(self):
        with mock.patch.object(render, "enumerate_panes", return_value=[]):
            self.assertEqual(render.render_once(home=self.tmp), 0)

    def test_render_once_writes_pane_cache(self):
        panes = [{"pid": 4242, "path": "/var/empty"}]
        with mock.patch.object(render, "enumerate_panes", return_value=panes), \
             mock.patch.object(render, "build_process_snapshot", return_value={}), \
             mock.patch.object(render, "load_sessions", return_value=[]):
            n = render.render_once(home=self.tmp)
        self.assertEqual(n, 1)
        envf = os.path.join(self.render_dir, "pane-4242.env")
        self.assertTrue(os.path.isfile(envf))
        with open(envf) as f:
            content = f.read()
        # non-Claude pane: only GIT_LINE + RENDER_TS, no MODEL
        self.assertIn("GIT_LINE=", content)
        self.assertIn("RENDER_TS=", content)
        self.assertNotIn("MODEL=", content)

    def _render_with(self, home, panes, sessions, ps_map):
        # HOME pinned to the temp dir so parse_transcript's settings.json effort
        # fallback can't read the real user's ~/.claude (keeps the test hermetic).
        with mock.patch.dict(os.environ, {"HOME": home}), \
             mock.patch.object(render, "enumerate_panes", return_value=panes), \
             mock.patch.object(render, "build_process_snapshot", return_value={
                 pid: {"pid": pid, "ppid": ppid, "command": "", "started_at": pid}
                 for pid, ppid in ps_map.items()
             }), \
             mock.patch.object(render, "load_sessions", return_value=sessions):
            return render.render_once(home=home)

    def _codex_rollout(self, name, thread_id, activity, model):
        path = os.path.join(
            self.tmp, ".codex", "sessions", "2026", "08", "23", name,
        )
        records = [
            {"timestamp": activity, "type": "session_meta",
             "payload": {"id": thread_id}},
            {"timestamp": activity, "type": "turn_context", "payload": {
                "model": model, "effort": "xhigh"}},
            {"timestamp": activity, "type": "event_msg", "payload": {
                "type": "task_started", "model_context_window": 100}},
            {"timestamp": activity, "type": "event_msg", "payload": {
                "type": "token_count", "info": {"last_token_usage": {
                    "total_tokens": 25}}, "rate_limits": {}}},
        ]
        _write(path, "\n".join(json.dumps(record) for record in records) + "\n")
        return path

    def _render_codex(
        self, candidates, pane_pid=4247, codex_pid=6002,
        pane_started=1, codex_started=2, now=100,
    ):
        processes = {
            pane_pid: {"pid": pane_pid, "ppid": 1, "command": "zsh",
                       "started_at": pane_started},
            codex_pid: {"pid": codex_pid, "ppid": pane_pid, "command": "codex",
                        "started_at": codex_started},
        }
        with mock.patch.object(render, "enumerate_panes", return_value=[
                 {"pid": pane_pid, "path": "/var/empty"}]), \
             mock.patch.object(render, "build_process_snapshot", return_value=processes), \
             mock.patch.object(render, "load_sessions", return_value=[]), \
             mock.patch.object(render, "resolve_codex_rollouts", return_value={
                 codex_pid: candidates}), \
             mock.patch.object(render.time, "time", return_value=now):
            render.render_once(home=self.tmp)
        return os.path.join(self.render_dir, f"pane-{pane_pid}.env")

    def test_render_once_model_from_bridge_when_transcript_has_no_assistant(self):
        # The /clear bug: the new transcript exists but has no assistant message
        # yet, so parse_transcript yields no model. The model must come from the
        # statusLine bridge so BOTH Claude lines render instead of going blank.
        home = self.tmp
        _write(os.path.join(home, ".claude", "projects", "-work-x", "sid-1.jsonl"),
               json.dumps({"type": "user", "sessionId": "sid-1",
                           "message": {"content": "hi"}}) + "\n")
        _write(os.path.join(home, ".cache", "tmux-status", "claude-ctx-sid-1.json"),
               json.dumps({"used_pct": 3, "model": "claude-opus-4-8"}))
        self._render_with(
            home,
            [{"pid": 4242, "path": "/var/empty"}],
            [{"pid": 5000, "cwd": "/work/x", "session_id": "sid-1", "file": "f"}],
            {5000: 4242},
        )
        with open(os.path.join(self.render_dir, "pane-4242.env")) as f:
            content = f.read()
        self.assertIn("AGENT_PROVIDER=claude", content)
        self.assertIn("AGENT_MODEL=claude-opus-4-8", content)
        self.assertIn("AGENT_SHORT_MODEL='Opus 4.8'", content)
        self.assertIn("AGENT_CONTEXT_PCT=3", content)

    def test_render_once_renders_from_bridge_when_transcript_absent(self):
        # Brand-new session: no transcript file yet. Bridge supplies the model so
        # the Claude line renders instead of going blank.
        home = self.tmp
        _write(os.path.join(home, ".cache", "tmux-status", "claude-ctx-sid-2.json"),
               json.dumps({"used_pct": 0, "model": "claude-sonnet-4-6"}))
        self._render_with(
            home,
            [{"pid": 4243, "path": "/var/empty"}],
            [{"pid": 5001, "cwd": "/work/y", "session_id": "sid-2", "file": "f"}],
            {5001: 4243},
        )
        with open(os.path.join(self.render_dir, "pane-4243.env")) as f:
            content = f.read()
        self.assertIn("AGENT_MODEL=claude-sonnet-4-6", content)
        self.assertNotIn("SESSION_COST", content)
        self.assertNotIn("DAILY_COST", content)

    def test_render_once_prefers_live_bridge_effort_over_transcript(self):
        # The transcript froze "/effort high", but the live statusLine bridge says
        # xhigh (a mid-session Shift+Tab change). The bar must show the live value.
        home = self.tmp
        _write(os.path.join(home, ".claude", "projects", "-work-z", "sid-3.jsonl"),
               "\n".join([
                   json.dumps({"type": "user", "sessionId": "sid-3", "message": {
                       "content": "<local-command-stdout>Set effort level to high</local-command-stdout>"}}),
                   json.dumps({"type": "assistant",
                               "message": {"model": "claude-opus-4-8", "content": []}}),
               ]) + "\n")
        _write(os.path.join(home, ".cache", "tmux-status", "claude-ctx-sid-3.json"),
               json.dumps({"used_pct": 5, "model": "claude-opus-4-8", "effort": "xhigh"}))
        self._render_with(
            home,
            [{"pid": 4244, "path": "/var/empty"}],
            [{"pid": 5002, "cwd": "/work/z", "session_id": "sid-3", "file": "f"}],
            {5002: 4244},
        )
        with open(os.path.join(self.render_dir, "pane-4244.env")) as f:
            content = f.read()
        self.assertIn("AGENT_EFFORT=xhigh", content)

    def test_render_once_writes_codex_status_from_exact_rollout(self):
        home = self.tmp
        rollout = os.path.join(home, ".codex", "sessions", "2026", "08", "18",
                               "rollout-one.jsonl")
        _write(rollout, "\n".join([
            json.dumps({"type": "turn_context", "payload": {
                "model": "gpt-5.6-sol", "effort": "xhigh"}}),
            json.dumps({"type": "event_msg", "payload": {
                "type": "task_started", "model_context_window": 100}}),
            json.dumps({"type": "event_msg", "payload": {
                "type": "token_count", "info": {"last_token_usage": {
                    "total_tokens": 25}}, "rate_limits": {}}}),
        ]) + "\n")
        processes = {
            4245: {"pid": 4245, "ppid": 1, "command": "zsh", "started_at": 1},
            6000: {"pid": 6000, "ppid": 4245, "command": "codex", "started_at": 2},
        }
        with mock.patch.object(render, "enumerate_panes", return_value=[
                 {"pid": 4245, "path": "/var/empty"}]), \
             mock.patch.object(render, "build_process_snapshot", return_value=processes), \
             mock.patch.object(render, "load_sessions", return_value=[]), \
             mock.patch.object(render, "resolve_codex_rollouts", return_value={6000: rollout}):
            render.render_once(home=home)
        with open(os.path.join(self.render_dir, "pane-4245.env")) as f:
            content = f.read()
        self.assertIn("AGENT_PROVIDER=codex", content)
        self.assertIn("AGENT_MODEL=gpt-5.6-sol", content)
        self.assertIn("AGENT_EFFORT=xhigh", content)
        self.assertIn("AGENT_CONTEXT_PCT=25", content)

    def test_render_once_codex_without_exact_rollout_is_blank(self):
        processes = {
            4246: {"pid": 4246, "ppid": 1, "command": "zsh", "started_at": 1},
            6001: {"pid": 6001, "ppid": 4246, "command": "codex", "started_at": 2},
        }
        with mock.patch.object(render, "enumerate_panes", return_value=[
                 {"pid": 4246, "path": "/var/empty"}]), \
             mock.patch.object(render, "build_process_snapshot", return_value=processes), \
             mock.patch.object(render, "load_sessions", return_value=[]), \
             mock.patch.object(render, "resolve_codex_rollouts", return_value={}):
            render.render_once(home=self.tmp)
        with open(os.path.join(self.render_dir, "pane-4246.env")) as f:
            content = f.read()
        self.assertNotIn("AGENT_PROVIDER=", content)
        self.assertIn("GIT_LINE=", content)

    def test_daemon_restart_restores_sticky_selection_from_sidecar(self):
        first = self._codex_rollout(
            "rollout-first.jsonl", "first", 20, "gpt-5.6-sol",
        )
        second = self._codex_rollout(
            "rollout-second.jsonl", "second", 10, "gpt-5.6-terra",
        )
        env_path = self._render_codex([first, second], now=100)
        with open(env_path) as source:
            original = source.read()
        self.assertIn("AGENT_MODEL=gpt-5.6-sol", original)
        sidecar = render._load_codex_selection(self.render_dir, 4247)
        self.assertEqual(sidecar["thread_id"], "first")

        # A new daemon has no in-memory state. Equal root activity can only
        # retain the first choice by loading the on-disk pane/Codex identity.
        _append_json(second, {
            "timestamp": 20,
            "type": "event_msg",
            "payload": {"type": "task_started"},
        })
        self._render_codex([first, second], now=200)
        with open(env_path) as source:
            restarted = source.read()
        self.assertEqual(restarted, original)
        self.assertIn("RENDER_TS=100", restarted)

    def test_malformed_evidence_keeps_last_known_agent_cache_stale(self):
        root = self._codex_rollout(
            "rollout-root.jsonl", "root", 20, "gpt-5.6-sol",
        )
        malformed = os.path.join(os.path.dirname(root), "rollout-malformed.jsonl")
        _write(malformed, "{}\n")
        env_path = self._render_codex([root], now=100)
        with open(env_path) as source:
            original = source.read()
        self._render_codex([root, malformed], now=200)
        with open(env_path) as source:
            retained = source.read()
        self.assertEqual(retained, original)
        self.assertIn("AGENT_PROVIDER=codex", retained)
        self.assertIn("RENDER_TS=100", retained)

    def test_codex_pid_change_clears_sticky_selection_on_ambiguity(self):
        first = self._codex_rollout(
            "rollout-first.jsonl", "first", 20, "gpt-5.6-sol",
        )
        second = self._codex_rollout(
            "rollout-second.jsonl", "second", 20, "gpt-5.6-terra",
        )
        env_path = self._render_codex([first], codex_pid=6002, now=100)
        self._render_codex([first, second], codex_pid=6003, now=200)
        with open(env_path) as source:
            reset = source.read()
        self.assertNotIn("AGENT_PROVIDER=", reset)
        self.assertIn("RENDER_TS=200", reset)
        self.assertFalse(os.path.exists(
            render._codex_selection_path(self.render_dir, 4247)
        ))

    def test_pane_pid_reuse_clears_sticky_selection_on_ambiguity(self):
        first = self._codex_rollout(
            "rollout-first.jsonl", "first", 20, "gpt-5.6-sol",
        )
        second = self._codex_rollout(
            "rollout-second.jsonl", "second", 20, "gpt-5.6-terra",
        )
        env_path = self._render_codex([first], pane_started=1, now=100)
        self._render_codex(
            [first, second], pane_started=3, codex_started=2, now=200,
        )
        with open(env_path) as source:
            reset = source.read()
        self.assertNotIn("AGENT_PROVIDER=", reset)
        self.assertIn("RENDER_TS=200", reset)


# ── PATH hardening (launchd/systemd minimal PATH) ──────────────────────────
class TestEnsurePath(unittest.TestCase):
    def test_adds_common_bin_dirs(self):
        with mock.patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}):
            render._ensure_path()
            parts = os.environ["PATH"].split(os.pathsep)
            self.assertIn("/opt/homebrew/bin", parts)
            self.assertIn("/usr/local/bin", parts)
            self.assertIn("/usr/bin", parts)  # existing entries preserved

    def test_does_not_duplicate(self):
        with mock.patch.dict(os.environ, {"PATH": "/opt/homebrew/bin:/usr/bin:/bin"}):
            render._ensure_path()
            parts = os.environ["PATH"].split(os.pathsep)
            self.assertEqual(parts.count("/opt/homebrew/bin"), 1)


# ── Vendored model drift guard ─────────────────────────────────────────────
class TestModelDrift(unittest.TestCase):
    def test_vendored_model_matches_scripts_copy(self):
        a = os.path.join(REPO_ROOT, "scripts", "tmux_claude_model.py")
        b = os.path.join(REPO_ROOT, "server", "tmux_status_server", "model.py")
        with open(a, "rb") as fa, open(b, "rb") as fb:
            self.assertEqual(fa.read(), fb.read(),
                             "server/tmux_status_server/model.py drifted from scripts/tmux_claude_model.py")


# ── Daemon wake / signal wiring ────────────────────────────────────────────
def _poll(predicate, timeout=2.0):
    """Wait until ``predicate()`` is true, yielding so pending main-thread signal
    handlers can run. Returns the final predicate value."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class TestSignalWake(unittest.TestCase):
    """The SIGUSR1 → immediate-tick path that ``tmux-status-poke`` relies on to
    close the cold-start gap on a fresh or ``/clear``'d session."""

    def setUp(self):
        # _install_signal_handlers mutates process-global dispositions; save them.
        self._orig = {
            s: signal.getsignal(s)
            for s in (signal.SIGTERM, signal.SIGINT, signal.SIGUSR1)
        }

    def tearDown(self):
        for s, h in self._orig.items():
            signal.signal(s, h)

    def test_sigusr1_sets_wake_not_shutdown(self):
        shutdown, wake = threading.Event(), threading.Event()
        render._install_signal_handlers(shutdown, wake)
        os.kill(os.getpid(), signal.SIGUSR1)
        self.assertTrue(_poll(wake.is_set), "SIGUSR1 did not set the wake event")
        self.assertFalse(shutdown.is_set(), "SIGUSR1 must not trigger shutdown")

    def test_sigterm_sets_shutdown_and_wake(self):
        shutdown, wake = threading.Event(), threading.Event()
        render._install_signal_handlers(shutdown, wake)
        os.kill(os.getpid(), signal.SIGTERM)
        self.assertTrue(_poll(shutdown.is_set), "SIGTERM did not set shutdown")
        self.assertTrue(wake.is_set(), "SIGTERM must also wake the loop to exit promptly")

    def test_once_mode_ignores_sigusr1(self):
        """A stray poke (SIGUSR1) must not kill the one-shot --once warm-up —
        ``tmux-status-poke``'s pkill fallback and the tmux re-source hooks can
        land one mid-pass, and the default disposition would terminate it."""
        import argparse
        args = argparse.Namespace(once=True, interval=5, log_level="INFO")
        seen = {}

        def grab(home=None, owner_pid=None):
            seen["disp"] = signal.getsignal(signal.SIGUSR1)

        with mock.patch.object(render, "_parse_args", return_value=args), \
             mock.patch.object(render, "render_once", side_effect=grab):
            render.main()
        self.assertEqual(seen["disp"], signal.SIG_IGN)

    def test_loop_renders_immediately_on_wake(self):
        """A set ``wake`` forces an early tick instead of sleeping the interval."""
        shutdown, wake = threading.Event(), threading.Event()
        calls = []
        second = threading.Event()

        def fake_render_once(home=None, owner_pid=None):
            calls.append(1)
            if len(calls) >= 2:
                second.set()
            return 0  # 0 ⇒ backoff path ⇒ would otherwise sleep the full interval

        with mock.patch.object(render, "render_once", side_effect=fake_render_once):
            # Huge interval: without the wake, a 2nd render would not arrive in time.
            t = threading.Thread(
                target=render._loop, args=(3600, None, 1234, shutdown, wake), daemon=True
            )
            t.start()
            try:
                # set() is sticky until the loop clears it → no lost-wakeup race.
                wake.set()
                self.assertTrue(second.wait(timeout=3.0),
                                "wake did not force an immediate second render")
            finally:
                shutdown.set()
                wake.set()
                t.join(timeout=3.0)
        self.assertFalse(t.is_alive(), "loop did not exit on shutdown")
        self.assertGreaterEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
