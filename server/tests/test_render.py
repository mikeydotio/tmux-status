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
class TestClaudeEnvLines(unittest.TestCase):
    def setUp(self):
        self.q = {"quota_status": "ok", "five_hour_pct": 6, "seven_day_pct": 64,
                  "five_hour_remain": "40m", "seven_day_remain": "10.0h",
                  "key_expiry_warn": False}

    def test_exact_lines(self):
        lines = render.claude_env_lines("claude-opus-4-8", "high", True, 37, self.q)
        self.assertEqual(lines[0], "MODEL=claude-opus-4-8")
        self.assertEqual(lines[1], "SHORT_MODEL='Opus 4.8'")  # space => shlex-quoted
        self.assertEqual(lines[2], "USED_PCT=37")             # bare int
        self.assertEqual(lines[3], "EFFORT=high")
        self.assertEqual(lines[4], "HAS_THINKING=1")
        # Cost keys are gone entirely (dollar display + computation removed).
        self.assertFalse(any(ln.startswith("SESSION_COST=") for ln in lines))
        self.assertFalse(any(ln.startswith("DAILY_COST=") for ln in lines))

    def test_thinking_flag_zero(self):
        lines = render.claude_env_lines("claude-opus-4-8", "auto", False, 0, self.q)
        self.assertEqual(lines[4], "HAS_THINKING=0")

    def test_quota_X_value_quoted(self):
        q = dict(self.q, five_hour_pct="X")
        lines = render.claude_env_lines("claude-opus-4-8", "auto", False, 0, q)
        self.assertIn("QUOTA_5H_PCT=X", lines)


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
        render._prune(self.render_dir, {100})
        names = set(os.listdir(self.render_dir))
        self.assertIn("pane-100.env", names)
        self.assertNotIn("pane-200.env", names)

    def test_render_once_no_tmux_returns_zero(self):
        with mock.patch.object(render, "enumerate_panes", return_value=[]):
            self.assertEqual(render.render_once(home=self.tmp), 0)

    def test_render_once_writes_pane_cache(self):
        panes = [{"pid": 4242, "path": "/var/empty"}]
        with mock.patch.object(render, "enumerate_panes", return_value=panes), \
             mock.patch.object(render, "build_ps_map", return_value={}), \
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
             mock.patch.object(render, "build_ps_map", return_value=ps_map), \
             mock.patch.object(render, "load_sessions", return_value=sessions):
            return render.render_once(home=home)

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
        self.assertIn("MODEL=claude-opus-4-8", content)
        self.assertIn("SHORT_MODEL='Opus 4.8'", content)
        self.assertIn("USED_PCT=3", content)

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
        self.assertIn("MODEL=claude-sonnet-4-6", content)
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
        self.assertIn("EFFORT=xhigh", content)


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
