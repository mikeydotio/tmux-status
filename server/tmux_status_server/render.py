"""tmux-status render daemon.

Precomputes the per-pane status-bar data (Claude model/effort/context/quota/cost
and git/path) on its own cadence and writes one small shell-sourceable cache file
per pane. The tmux ``#()`` status scripts then become fork-free readers that just
``source`` the cache and ``printf`` — moving ALL heavy work (process-tree walks,
transcript parsing, quota HTTP, cost ``os.walk``, git subprocesses) off the tmux
render path so it can never pile up.

The cache contract is the exact ``KEY=value`` set the old ``tmux-claude-status``
heredoc emitted for ``eval`` (model, quota, cost), plus ``GIT_LINE`` and
``RENDER_TS``. Because the readers keep the original bash formatting unchanged,
status-bar output stays byte-for-byte identical.

Design mirrors ``server.py``: a single managed instance (launchd ``KeepAlive`` /
systemd ``Restart``) plus an advisory flock singleton guard, SIGTERM/SIGINT clean
shutdown and SIGUSR1 immediate-tick. Stdlib only.
"""

import argparse
import glob
import json
import logging
import math
import os
import platform
import re
import shlex
import signal
import subprocess
import threading
import time
import urllib.request
from datetime import datetime, timezone

from tmux_status_server.model import format_model
from tmux_status_server.singleton import acquire_singleton

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL = 5
MAX_BACKOFF = 60
RENDER_DIRNAME = "render"
TRANSCRIPT_TAIL_BYTES = 512000

# launchd (macOS) and systemd (Linux) start daemons with a minimal PATH that
# usually omits Homebrew/local bin dirs — so `tmux` and `git` would not resolve
# and the daemon would see zero panes and render nothing. Make sure the common
# locations are searched regardless of the inherited PATH.
_EXTRA_PATH = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]


def _ensure_path():
    """Prepend common bin dirs (not already present) so tmux/git resolve."""
    cur = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d]
    missing = [d for d in _EXTRA_PATH if d not in cur]
    os.environ["PATH"] = os.pathsep.join(missing + cur) if missing else os.environ.get("PATH", "")


# ── Process tree ───────────────────────────────────────────────────────────
def _parse_ps_output(text):
    """Parse ``ps -axo pid=,ppid=`` output into a ``{pid: ppid}`` map."""
    ps_map = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            ps_map[int(parts[0])] = int(parts[1])
        except ValueError:
            continue
    return ps_map


def _parse_process_output(text):
    """Parse ``ps`` rows into PID-keyed process metadata.

    Expected columns are ``pid ppid lstart comm``. ``lstart`` is five fields on
    both BSD/macOS and procps/Linux, leaving the command at field eight. A bad
    row is ignored so a single disappearing process cannot abort a render tick.
    """
    processes = {}
    for line in text.splitlines():
        parts = line.split(None, 7)
        if len(parts) != 8:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
            started = datetime.strptime(
                " ".join(parts[2:7]), "%a %b %d %H:%M:%S %Y"
            ).timestamp()
        except (TypeError, ValueError, OverflowError):
            continue
        processes[pid] = {
            "pid": pid,
            "ppid": ppid,
            "started_at": started,
            "command": parts[7],
        }
    return processes


def build_process_snapshot():
    """Take the one process-table snapshot used by an entire render tick."""
    try:
        out = subprocess.run(
            ["ps", "-axo", "pid=,ppid=,lstart=,comm="],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return {}
    return _parse_process_output(out.stdout)


def build_ps_map():
    """Compatibility helper returning only PID→PPID from a fresh snapshot."""
    return {pid: process["ppid"] for pid, process in build_process_snapshot().items()}


def walk_to_ancestor(pid, ancestor, ps_map, max_depth=64):
    """Return True if ``ancestor`` is ``pid`` or one of its ancestors.

    In-memory walk of the PID→PPID map, replacing the old shell loop that forked
    ``ps -o ppid=`` at every step. ``max_depth`` guards against a corrupt/cyclic
    map. Mirrors the original loop: stop (no match) at pid 1/0 or off the map.
    """
    try:
        cur = int(pid)
        ancestor = int(ancestor)
    except (TypeError, ValueError):
        return False
    for _ in range(max_depth):
        if not cur or cur in (0, 1):
            return False
        if cur == ancestor:
            return True
        nxt = ps_map.get(cur)
        if nxt is None:
            return False
        cur = nxt
    return False


def _distance_to_ancestor(pid, ancestor, ps_map, max_depth=64):
    """Return descendant distance to ``ancestor``, or ``None`` without a match."""
    try:
        cur = int(pid)
        ancestor = int(ancestor)
    except (TypeError, ValueError):
        return None
    for distance in range(max_depth + 1):
        if cur == ancestor:
            return distance
        if not cur or cur in (0, 1):
            return None
        cur = ps_map.get(cur)
        if cur is None:
            return None
    return None


def _is_codex_command(command):
    """True only for known Codex executable names, never arbitrary arguments."""
    name = os.path.basename(str(command or "")).lower()
    return name == "codex" or name.startswith("codex-")


def select_agent_process(pane_pid, claude_sessions, processes):
    """Select the active agent descendant for a pane.

    The closest descendant to the pane process wins. Equal-depth candidates are
    ordered by process start time (newest first), then PID for determinism.
    Claude candidates come from its authoritative live session files; Codex
    candidates come from exact executable names in the shared process snapshot.
    """
    ps_map = {pid: process.get("ppid") for pid, process in processes.items()}
    candidates = []
    for session in claude_sessions:
        pid = session.get("pid")
        distance = _distance_to_ancestor(pid, pane_pid, ps_map)
        if distance is None:
            continue
        process = processes.get(pid, {})
        candidates.append({
            "provider": "claude",
            "pid": pid,
            "distance": distance,
            "started_at": process.get("started_at", 0),
            "session": session,
        })
    for pid, process in processes.items():
        if not _is_codex_command(process.get("command")):
            continue
        distance = _distance_to_ancestor(pid, pane_pid, ps_map)
        if distance is None:
            continue
        candidates.append({
            "provider": "codex",
            "pid": pid,
            "distance": distance,
            "started_at": process.get("started_at", 0),
        })
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda candidate: (
            candidate["distance"],
            -float(candidate.get("started_at") or 0),
            -int(candidate["pid"]),
        ),
    )


def _valid_rollout_path(path, codex_home):
    """Return a canonical Codex rollout path, or ``None`` when out of scope."""
    if not path or not str(path).endswith(".jsonl"):
        return None
    try:
        candidate = os.path.realpath(path)
        sessions_root = os.path.realpath(os.path.join(codex_home, "sessions"))
        if os.path.commonpath((candidate, sessions_root)) != sessions_root:
            return None
        if not os.path.isfile(candidate):
            return None
    except (OSError, ValueError):
        return None
    return candidate


def _single_rollout(paths, codex_home):
    valid = {
        resolved for path in paths
        if (resolved := _valid_rollout_path(path, codex_home)) is not None
    }
    return next(iter(valid)) if len(valid) == 1 else None


def _parse_lsof_rollouts(text, requested_pids, codex_home):
    paths_by_pid = {int(pid): [] for pid in requested_pids}
    current_pid = None
    for line in text.splitlines():
        if line.startswith("p"):
            try:
                current_pid = int(line[1:])
            except ValueError:
                current_pid = None
        elif line.startswith("n") and current_pid in paths_by_pid:
            paths_by_pid[current_pid].append(line[1:])
    return {
        pid: rollout
        for pid, paths in paths_by_pid.items()
        if (rollout := _single_rollout(paths, codex_home)) is not None
    }


def resolve_codex_rollouts(pids, codex_home, system_name=None, proc_root="/proc"):
    """Resolve exact open Codex rollout files for a batch of process IDs.

    Linux reads descriptor symlinks directly. macOS performs one `lsof` call for
    the full PID batch. A PID is returned only when exactly one unique rollout
    under ``CODEX_HOME/sessions`` is open; ambiguity intentionally fails safe.
    """
    requested = sorted({int(pid) for pid in pids})
    if not requested:
        return {}
    system_name = system_name or platform.system()
    if system_name == "Linux":
        resolved = {}
        for pid in requested:
            fd_dir = os.path.join(proc_root, str(pid), "fd")
            paths = []
            try:
                fds = os.listdir(fd_dir)
            except OSError:
                continue
            for fd in fds:
                try:
                    paths.append(os.readlink(os.path.join(fd_dir, fd)))
                except OSError:
                    continue
            rollout = _single_rollout(paths, codex_home)
            if rollout is not None:
                resolved[pid] = rollout
        return resolved
    if system_name == "Darwin":
        try:
            out = subprocess.run(
                ["lsof", "-n", "-F", "pn", "-p", ",".join(map(str, requested))],
                capture_output=True, text=True, timeout=5,
            )
        except Exception:
            return {}
        return _parse_lsof_rollouts(out.stdout, requested, codex_home)
    return {}


# ── Codex rollout parsing ─────────────────────────────────────────────────
def _empty_agent_status(provider):
    return {
        "provider": provider,
        "model": None,
        "effort": None,
        "has_thinking": None,
        "context_pct": None,
        "quota_slots": [],
        "quota_status": "none",
        "quota_warn": False,
    }


def _read_tail_text(path, max_bytes=TRANSCRIPT_TAIL_BYTES):
    """Read a bounded file tail, tolerating a partial first UTF-8/JSONL record."""
    with open(path, "rb") as source:
        source.seek(0, 2)
        size = source.tell()
        chunk_size = min(size, max_bytes)
        source.seek(size - chunk_size)
        return source.read().decode("utf-8", errors="replace")


def _rounded_percent(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return max(0, min(100, int(round(value))))


def format_window_duration(window_minutes):
    """Format a Codex quota window as a stable compact duration label."""
    if isinstance(window_minutes, bool) or not isinstance(window_minutes, (int, float)):
        return None
    if not math.isfinite(window_minutes) or window_minutes <= 0:
        return None
    minutes = int(window_minutes)
    if minutes != window_minutes:
        return None
    if minutes % 1440 == 0:
        return f"{minutes // 1440}d"
    if minutes % 60 == 0:
        return f"{minutes // 60}h"
    return f"{minutes}m"


def _format_reset_epoch(resets_at, now=None):
    if isinstance(resets_at, bool) or not isinstance(resets_at, (int, float)):
        return None
    if not math.isfinite(resets_at):
        return None
    now = time.time() if now is None else now
    secs = max(0, int(resets_at - now))
    if secs >= 86400:
        return f"{secs / 86400:.1f}d"
    if secs >= 3600:
        return f"{secs / 3600:.1f}h"
    return f"{secs // 60}m"


def _codex_quota_slot(window, now=None):
    if not isinstance(window, dict):
        return None
    duration = format_window_duration(window.get("window_minutes"))
    pct = _rounded_percent(window.get("used_percent"))
    reset = _format_reset_epoch(window.get("resets_at"), now=now)
    if duration is None or pct is None or reset is None:
        return None
    return {"duration": duration, "reset": reset, "pct": pct}


def parse_codex_rollout(rollout, now=None):
    """Parse the latest Codex turn/context/quota metrics from a rollout tail."""
    status = _empty_agent_status("codex")
    try:
        data = _read_tail_text(rollout)
    except Exception:
        return status

    turn_context = None
    task_started = None
    token_count = None
    for line in reversed(data.splitlines()):
        try:
            record = json.loads(line)
        except Exception:
            continue
        if not isinstance(record, dict):
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        if turn_context is None and record.get("type") == "turn_context":
            turn_context = payload
        elif record.get("type") == "event_msg":
            if task_started is None and payload.get("type") == "task_started":
                task_started = payload
            elif token_count is None and payload.get("type") == "token_count":
                token_count = payload
        if turn_context is not None and task_started is not None and token_count is not None:
            break

    if turn_context is not None:
        model = turn_context.get("model")
        effort = turn_context.get("effort")
        status["model"] = model if isinstance(model, str) and model else None
        status["effort"] = effort if isinstance(effort, str) and effort else None

    context_window = task_started.get("model_context_window") if task_started else None
    usage = token_count.get("info") if token_count else None
    usage = usage.get("last_token_usage") if isinstance(usage, dict) else None
    total_tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
    if (
        isinstance(context_window, (int, float))
        and not isinstance(context_window, bool)
        and math.isfinite(context_window)
        and context_window > 0
        and isinstance(total_tokens, (int, float))
        and not isinstance(total_tokens, bool)
        and math.isfinite(total_tokens)
    ):
        status["context_pct"] = _rounded_percent(total_tokens / context_window * 100)

    limits = token_count.get("rate_limits") if token_count else None
    if isinstance(limits, dict):
        for key in ("primary", "secondary"):
            slot = _codex_quota_slot(limits.get(key), now=now)
            if slot is not None:
                status["quota_slots"].append(slot)
        if status["quota_slots"]:
            status["quota_status"] = (
                "blocked" if limits.get("rate_limit_reached_type") else "ok"
            )
    return status


# ── Claude session discovery ───────────────────────────────────────────────
def load_sessions(claude_dir):
    """Read every ``~/.claude/sessions/*.json`` once, in-process.

    Returns a list of ``{pid, cwd, session_id, file}`` dicts (replaces the
    per-file ``python3 -c`` cold starts). Unreadable/legacy files are skipped
    silently. ``session_id`` is Claude's live conversation id — it is rewritten
    in place on ``/clear`` (same pid, new id), so it is the authoritative,
    lag-free identity the daemon keys the transcript and context bridge on
    (the transcript's own ``sessionId`` only appears once a line is written).
    """
    sessions = []
    for pidfile in glob.glob(os.path.join(claude_dir, "sessions", "*.json")):
        try:
            with open(pidfile) as f:
                d = json.load(f)
            pid = d.get("pid")
            if pid is None:
                continue
            sessions.append({
                "pid": int(pid),
                "cwd": d.get("cwd"),
                "session_id": d.get("sessionId") or "",
                "file": pidfile,
            })
        except Exception:
            continue
    return sessions


def resolve_pane_session(pane_pid, sessions, ps_map):
    """Find the Claude session whose process tree contains ``pane_pid``.

    First ancestor match wins (deterministic — a pane is in at most one tree).
    Returns the session dict or ``None``.
    """
    for s in sessions:
        if walk_to_ancestor(s["pid"], pane_pid, ps_map):
            return s
    return None


def find_transcript(cwd, claude_dir, session_id=None):
    """Map a session to its transcript ``.jsonl``.

    Transcript files are named ``{sessionId}.jsonl``, so when ``session_id`` is
    known (from the live session file) we resolve the EXACT transcript for this
    pane's session and return ``None`` if it does not exist yet — never falling
    back to the newest file, which would belong to a different (prior) session
    and mis-attribute its model/cost. With no ``session_id`` (legacy callers) we
    keep the original newest-in-cwd behavior (``ls -t | head -1``).
    """
    if not cwd:
        return None
    project_dir = os.path.join(claude_dir, "projects", cwd.replace("/", "-"))
    if not os.path.isdir(project_dir):
        return None
    if session_id:
        exact = os.path.join(project_dir, f"{session_id}.jsonl")
        return exact if os.path.isfile(exact) else None
    candidates = glob.glob(os.path.join(project_dir, "*.jsonl"))
    if not candidates:
        return None
    try:
        return max(candidates, key=lambda p: os.stat(p).st_mtime)
    except OSError:
        return None


def parse_transcript(transcript):
    """Parse model, effort, thinking flag and conversation id from the tail.

    Port of the old heredoc's reverse scan of the last 512KB. Each line is
    guarded so one malformed record can never kill the long-running daemon.
    """
    model = ""
    effort = ""
    has_thinking = False
    conversation_id = ""
    try:
        with open(transcript, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            chunk_size = min(size, TRANSCRIPT_TAIL_BYTES)
            f.seek(size - chunk_size)
            data = f.read().decode("utf-8", errors="replace")
    except Exception:
        return {"model": "", "effort": "auto", "has_thinking": False, "conversation_id": ""}

    found_model = False
    found_effort = False
    for line in reversed(data.strip().split("\n")):
        if found_model and found_effort and conversation_id:
            break
        try:
            d = json.loads(line)
            if not isinstance(d, dict):
                continue

            if not conversation_id and "sessionId" in d:
                conversation_id = d["sessionId"]

            if not found_model and d.get("type") == "assistant":
                msg = d.get("message", {})
                if isinstance(msg, dict) and "model" in msg:
                    model = msg["model"]
                    found_model = True
                    content = msg.get("content", [])
                    if isinstance(content, list):
                        has_thinking = any(
                            isinstance(c, dict) and c.get("type") == "thinking"
                            for c in content
                        )

            if not found_effort and d.get("type") == "user":
                msg = d.get("message", {})
                content = msg.get("content", "") if isinstance(msg, dict) else ""
                if isinstance(content, str) and "<local-command-stdout>" in content:
                    tags = re.findall(
                        r"<local-command-stdout>(.*?)</local-command-stdout>", content
                    )
                    for tag in reversed(tags):
                        m = re.search(r"(?:Set effort level to |Effort level: )(\w+)", tag)
                        if m:
                            effort = m.group(1)
                            found_effort = True
                            break
        except Exception:
            continue

    if not found_effort:
        try:
            with open(os.path.join(os.path.expanduser("~"), ".claude", "settings.json")) as sf:
                _settings = json.load(sf)
            _el = _settings.get("effortLevel", "")
            if _el:
                effort = _el
        except Exception:
            pass

    if not effort:
        effort = "auto"
    return {
        "model": model,
        "effort": effort,
        "has_thinking": has_thinking,
        "conversation_id": conversation_id,
    }


def read_bridge(conversation_id, home, default=0):
    """Read the statusline-hook bridge file (tmux-status dir, then legacy coderig).

    Returns ``{"used_pct", "model", "effort", "has_thinking"}``. The hook writes
    these in real time — including on a fresh/``/clear``'d session BEFORE the
    transcript has any assistant message — so the bridge is what lets the daemon
    render the Claude lines without waiting for the first reply. Crucially it also
    carries the LIVE session ``effort`` (the statusLine payload's ``effort.level``,
    which reflects mid-session Shift+Tab changes) and ``thinking`` toggle, so the
    status bar tracks the header instead of a frozen ``/effort`` transcript echo.
    Legacy/older bridges predate these keys, so ``model``/``effort`` default to
    ``""`` and ``has_thinking`` to ``None`` there (forcing the transcript
    fallback). An empty ``conversation_id`` short-circuits with the defaults and
    touches no disk, preserving the non-Claude-pane contract.
    """
    result = {"used_pct": default, "model": "", "effort": "", "has_thinking": None}
    if not conversation_id:
        return result
    for cache_dir in (
        os.path.join(home, ".cache", "tmux-status"),
        os.path.join(home, ".cache", "coderig"),
    ):
        bridge = os.path.join(cache_dir, f"claude-ctx-{conversation_id}.json")
        try:
            with open(bridge) as bf:
                bd = json.load(bf)
        except Exception:
            continue
        result["used_pct"] = bd.get("used_pct", default)
        result["model"] = bd.get("model", "") or ""
        result["effort"] = bd.get("effort", "") or ""
        _thinking = bd.get("thinking", None)
        result["has_thinking"] = _thinking if isinstance(_thinking, bool) else None
        return result
    return result


def read_context_pct(conversation_id, home, default=0):
    """Context % from the statusline-hook bridge file (thin wrapper on read_bridge)."""
    return read_bridge(conversation_id, home, default)["used_pct"]


# ── Settings ───────────────────────────────────────────────────────────────
def _expand_home_path(value, home):
    if value == "~":
        return home
    if value.startswith("~/"):
        return os.path.join(home, value[2:])
    return value


def load_settings(home):
    """Read daemon settings from ``~/.config/tmux-status/settings.conf``."""
    config_dir = os.environ.get("XDG_CONFIG_HOME", os.path.join(home, ".config"))
    settings_file = os.path.join(config_dir, "tmux-status", "settings.conf")
    s = {
        "quota_bridge": os.path.join(home, ".cache", "tmux-status", "claude-quota.json"),
        "quota_source": "http://127.0.0.1:7850",
        "quota_api_key": "",
        "quota_cache_ttl": 30,
        "quota_max_stale": 300,
        "codex_home": os.environ.get("CODEX_HOME") or os.path.join(home, ".codex"),
    }
    try:
        with open(settings_file) as sf:
            for line in sf:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k == "QUOTA_DATA_PATH":
                    v = os.path.expanduser(v)
                    if v:
                        s["quota_bridge"] = v
                elif k == "QUOTA_SOURCE":
                    s["quota_source"] = v
                elif k == "QUOTA_API_KEY":
                    s["quota_api_key"] = v
                elif k == "QUOTA_CACHE_TTL":
                    try:
                        s["quota_cache_ttl"] = int(v)
                    except ValueError:
                        pass
                elif k == "QUOTA_MAX_STALE":
                    try:
                        s["quota_max_stale"] = int(v)
                    except ValueError:
                        pass
                elif k == "CODEX_HOME" and v:
                    s["codex_home"] = _expand_home_path(v, home)
    except Exception:
        pass
    return s


# ── Quota ──────────────────────────────────────────────────────────────────
def _maybe_fetch_quota(source_url, api_key, cache_ttl, cache_path):
    """Fetch quota from the server, write to the disk cache. Silent on failure."""
    if not source_url:
        return
    if cache_ttl > 0:
        try:
            if time.time() - os.stat(cache_path).st_mtime < cache_ttl:
                return
        except FileNotFoundError:
            pass
    try:
        req = urllib.request.Request(source_url.rstrip("/") + "/quota")
        if api_key:
            req.add_header("X-API-Key", api_key)
        resp = urllib.request.urlopen(req, timeout=3)
        data = resp.read()
        json.loads(data)  # validate JSON
        cache_dir = os.path.dirname(cache_path)
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)
        tmp = f"{cache_path}.{os.getpid()}.tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, cache_path)
    except Exception:
        pass


def fmt_reset(iso_str):
    """Format an ISO reset timestamp as a compact remaining-time string."""
    if not iso_str:
        return "?"
    try:
        reset = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        delta = reset - datetime.now(timezone.utc)
        secs = max(0, int(delta.total_seconds()))
        if secs >= 86400:
            return f"{secs / 86400:.1f}d"
        elif secs >= 3600:
            return f"{secs / 3600:.1f}h"
        else:
            return f"{secs // 60}m"
    except Exception:
        return "?"


def fmt_remain(iso_str, status, full_label):
    """ok+null reset = window full; stale = uncertain; else = broken upstream."""
    if status == "ok":
        return full_label if not iso_str else fmt_reset(iso_str)
    if status == "stale":
        return "?"
    return "X"


def _key_expiry_warn(key_expires_at):
    """True when the session key expires within 24h."""
    if key_expires_at:
        try:
            exp = datetime.fromisoformat(key_expires_at.replace("Z", "+00:00"))
            return (exp - datetime.now(timezone.utc)).total_seconds() < 86400
        except Exception:
            pass
    return False


def compute_quota_vars(settings, home):
    """Fetch+parse quota into the status variables (global; same for all panes)."""
    quota_bridge = settings["quota_bridge"]
    _maybe_fetch_quota(
        settings["quota_source"], settings["quota_api_key"],
        settings["quota_cache_ttl"], quota_bridge,
    )
    if not os.path.exists(quota_bridge):
        quota_bridge = None

    quota_status = "none"
    five_hour_pct = 0
    five_hour_reset = ""
    seven_day_pct = 0
    seven_day_reset = ""
    key_expires_at = ""

    if quota_bridge:
        qd = None
        for _attempt in range(3):
            try:
                with open(quota_bridge) as _qf:
                    qd = json.load(_qf)
                break
            except Exception:
                time.sleep(0.03)
        if qd is None:
            quota_status = "stale"
            five_hour_pct = "X"
            seven_day_pct = "X"
        else:
            quota_status = qd.get("status", "none")
            key_expires_at = qd.get("expires_at", "")
            if quota_status == "ok":
                fh = qd.get("five_hour", {})
                fh_util = fh.get("utilization", 0)
                five_hour_pct = "X" if fh_util is None or fh_util == "X" else round(fh_util)
                five_hour_reset = fh.get("resets_at", "")
                sd = qd.get("seven_day", {})
                sd_util = sd.get("utilization", 0)
                seven_day_pct = "X" if sd_util is None or sd_util == "X" else round(sd_util)
                seven_day_reset = sd.get("resets_at", "")
            elif quota_status == "error":
                five_hour_pct = "X"
                seven_day_pct = "X"
                fh = qd.get("five_hour", {})
                five_hour_reset = fh.get("resets_at", "")
                sd = qd.get("seven_day", {})
                seven_day_reset = sd.get("resets_at", "")
            else:
                five_hour_pct = "X"
                seven_day_pct = "X"

    if quota_bridge and quota_status == "ok" and settings["quota_max_stale"] > 0:
        try:
            _cache_age = time.time() - os.stat(quota_bridge).st_mtime
            if _cache_age > settings["quota_max_stale"]:
                quota_status = "stale"
                five_hour_pct = "X"
                seven_day_pct = "X"
        except Exception:
            pass

    return {
        "quota_status": quota_status,
        "five_hour_pct": five_hour_pct,
        "seven_day_pct": seven_day_pct,
        "five_hour_remain": fmt_remain(five_hour_reset, quota_status, "5h"),
        "seven_day_remain": fmt_remain(seven_day_reset, quota_status, "7d"),
        "key_expiry_warn": _key_expiry_warn(key_expires_at),
    }


# ── Git ────────────────────────────────────────────────────────────────────
def _git(path, args, timeout=3):
    try:
        return subprocess.run(
            ["git", "-C", path] + args,
            capture_output=True, text=True, timeout=timeout,
        )
    except Exception:
        return None


def _git_ok(path, args):
    r = _git(path, args)
    return r is not None and r.returncode == 0


def _git_changed(path, args):
    """True when ``git <args>`` reports changes (non-zero exit), matching the
    shell's ``! git ... --quiet`` (a git error counts as changed, as in the
    original)."""
    r = _git(path, args)
    if r is None:
        return True
    return r.returncode != 0


def _git_out(path, args):
    r = _git(path, args)
    if r is None or r.returncode != 0:
        return ""
    return r.stdout.strip()


def compute_git_line(path, home):
    """Reproduce ``tmux-git-status`` output for a pane path (path-only outside a repo)."""
    if not path:
        return ""
    # The original bash `${dir/$HOME/\~}` emits a LITERAL backslash-tilde for
    # paths at/under $HOME (a pre-existing quirk). Reproduce it exactly so the
    # rendered output stays byte-for-byte identical.
    rel = path.replace(home, "\\~", 1) if home else path

    if not _git_ok(path, ["rev-parse", "--is-inside-work-tree"]):
        return rel

    branch = _git_out(path, ["symbolic-ref", "--short", "HEAD"]) or _git_out(
        path, ["rev-parse", "--short", "HEAD"]
    )

    dirty = ""
    if _git_changed(path, ["diff", "--quiet"]) or _git_changed(path, ["diff", "--cached", "--quiet"]):
        dirty = "dirty"
    elif _git_out(path, ["ls-files", "--others", "--exclude-standard", path]):
        dirty = "dirty"

    ahead_behind = _git_out(path, ["rev-list", "--left-right", "--count", "HEAD...@{upstream}"])
    if ahead_behind:
        fields = ahead_behind.split("\t")
        ahead = fields[0] if len(fields) > 0 else ""
        behind = fields[1] if len(fields) > 1 else ""
        parts = []
        if dirty == "dirty":
            parts.append("dirty")
        try:
            if int(ahead) > 0:
                parts.append(f"↑{ahead}")
        except ValueError:
            pass
        try:
            if int(behind) > 0:
                parts.append(f"↓{behind}")
        except ValueError:
            pass
        if not parts:
            parts.append("clean")
        status_str = ",".join(parts)  # bash joins ${parts[*]} on IFS first char ','
    else:
        status_str = dirty if dirty else "clean"

    return f"{rel} : {branch} ({status_str})"


# ── Provider adapters / env assembly ───────────────────────────────────────
def build_claude_status(session, home, claude_dir):
    """Adapt Claude's existing transcript+bridge precedence to a shared record."""
    sid = session.get("session_id") or ""
    transcript = find_transcript(session.get("cwd"), claude_dir, sid)
    bridge = read_bridge(sid, home)
    parsed = parse_transcript(transcript) if transcript else {
        "model": "", "effort": "auto", "has_thinking": False,
        "conversation_id": "",
    }
    model = parsed["model"] or bridge["model"]
    if not model:
        # Preserve Claude's historical blank-before-model behavior.
        return None
    status = _empty_agent_status("claude")
    status.update({
        "model": model,
        "effort": bridge["effort"] or parsed["effort"],
        "has_thinking": (
            bridge["has_thinking"]
            if bridge["has_thinking"] is not None
            else parsed["has_thinking"]
        ),
        "context_pct": bridge["used_pct"],
    })
    return status


def attach_claude_quota(status, quota_vars):
    """Attach Claude's existing global quota values as normalized slots."""
    status["quota_status"] = quota_vars["quota_status"]
    status["quota_warn"] = quota_vars["key_expiry_warn"]
    if quota_vars["quota_status"] not in ("none", "no_key"):
        status["quota_slots"] = [
            {
                "duration": "5h",
                "reset": quota_vars["five_hour_remain"],
                "pct": quota_vars["five_hour_pct"],
            },
            {
                "duration": "7d",
                "reset": quota_vars["seven_day_remain"],
                "pct": quota_vars["seven_day_pct"],
            },
        ]


def _shell_value(value):
    return shlex.quote("" if value is None else str(value))


def agent_env_lines(status):
    """Build the provider-neutral ``AGENT_*`` cache contract."""
    thinking = status.get("has_thinking")
    slots = list(status.get("quota_slots") or [])[:2]
    while len(slots) < 2:
        slots.append({})
    lines = [
        "AGENT_PROVIDER=" + _shell_value(status.get("provider")),
        "AGENT_MODEL=" + _shell_value(status.get("model")),
        "AGENT_SHORT_MODEL=" + _shell_value(format_model(status.get("model") or "")),
        "AGENT_EFFORT=" + _shell_value(status.get("effort")),
        "AGENT_HAS_THINKING=" + (
            "''" if thinking is None else ("1" if thinking else "0")
        ),
        "AGENT_CONTEXT_PCT=" + _shell_value(status.get("context_pct")),
        "AGENT_QUOTA_STATUS=" + _shell_value(status.get("quota_status") or "none"),
        "AGENT_QUOTA_WARN=" + ("1" if status.get("quota_warn") else "0"),
    ]
    for index, slot in enumerate(slots, start=1):
        prefix = f"AGENT_QUOTA_{index}_"
        lines.extend([
            prefix + "DURATION=" + _shell_value(slot.get("duration")),
            prefix + "RESET=" + _shell_value(slot.get("reset")),
            prefix + "PCT=" + _shell_value(slot.get("pct")),
        ])
    return lines


# ── Panes / cache ──────────────────────────────────────────────────────────
def enumerate_panes():
    """All panes across the tmux server as ``[{pid, path}]`` (one fork per tick)."""
    try:
        out = subprocess.run(
            ["tmux", "list-panes", "-a", "-F", "#{pane_pid}\t#{pane_current_path}"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return []
    if out.returncode != 0:
        return []
    panes = []
    for line in out.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        try:
            pid = int(parts[0])
        except (ValueError, IndexError):
            continue
        panes.append({"pid": pid, "path": parts[1] if len(parts) > 1 else ""})
    return panes


def _atomic_write(path, content, owner_pid):
    tmp = f"{path}.{owner_pid}.tmp"
    with open(tmp, "w") as f:
        f.write(content)
    os.replace(tmp, path)


def _prune(render_dir, live_pids):
    """Remove cache files for panes that no longer exist (pid-reuse safety)."""
    try:
        names = os.listdir(render_dir)
    except OSError:
        return
    for name in names:
        if not (name.startswith("pane-") and name.endswith(".env")):
            continue
        try:
            pid = int(name[len("pane-"):-len(".env")])
        except ValueError:
            continue
        if pid not in live_pids:
            try:
                os.remove(os.path.join(render_dir, name))
            except OSError:
                pass


def render_once(home=None, owner_pid=None):
    """Render one full tick. Returns the pane count (0 ⇒ no tmux server ⇒ back off)."""
    home = home or os.path.expanduser("~")
    owner_pid = owner_pid or os.getpid()
    claude_dir = os.path.join(home, ".claude")
    render_dir = os.path.join(home, ".cache", "tmux-status", RENDER_DIRNAME)
    render_ts = int(time.time())

    panes = enumerate_panes()
    if not panes:
        return 0

    os.makedirs(render_dir, exist_ok=True)
    settings = load_settings(home)
    processes = build_process_snapshot()
    sessions = load_sessions(claude_dir)

    # Pass 1 — select one provider process per pane from the shared snapshot.
    # Resolve every selected Codex PID in one platform operation (one batched
    # lsof on macOS; direct fd reads on Linux), never by guessing a recent file.
    selected = []
    for pane in panes:
        selected.append((pane, select_agent_process(pane["pid"], sessions, processes)))
    codex_rollouts = resolve_codex_rollouts(
        [agent["pid"] for _, agent in selected if agent and agent["provider"] == "codex"],
        settings["codex_home"],
    )

    # Pass 2 — adapt the provider's exact local source into one status record.
    resolved = []
    claude_statuses = []
    for pane, agent in selected:
        status = None
        if agent and agent["provider"] == "claude":
            status = build_claude_status(agent["session"], home, claude_dir)
            if status is not None:
                claude_statuses.append(status)
        elif agent and agent["provider"] == "codex":
            rollout = codex_rollouts.get(agent["pid"])
            if rollout:
                status = parse_codex_rollout(rollout)
        resolved.append((pane, status))

    # Claude quota remains global and uses only the existing Claude quota server.
    # Codex quota is already local to each rollout and never traverses that path.
    if claude_statuses:
        quota_vars = compute_quota_vars(settings, home)
        for status in claude_statuses:
            attach_claude_quota(status, quota_vars)

    # Pass 3 — pure assembly + atomic write.
    live_pids = set()
    for pane, status in resolved:
        live_pids.add(pane["pid"])
        lines = []
        if status is not None:
            lines.extend(agent_env_lines(status))
        lines.append("GIT_LINE=" + shlex.quote(compute_git_line(pane["path"], home)))
        lines.append("RENDER_TS=" + str(render_ts))
        try:
            _atomic_write(
                os.path.join(render_dir, f"pane-{pane['pid']}.env"),
                "\n".join(lines) + "\n", owner_pid,
            )
        except OSError:
            logger.exception("Failed writing cache for pane %s", pane["pid"])

    _prune(render_dir, live_pids)
    return len(panes)


# ── Daemon ─────────────────────────────────────────────────────────────────
def _install_signal_handlers(shutdown, wake):
    """Wire SIGTERM/SIGINT → ``shutdown`` and SIGUSR1 → immediate ``wake``.

    Split out of ``run`` so the signal→event wiring is unit-testable on its own.
    Must run on the main thread (``signal.signal`` requires it).
    """
    def _sigterm(signum, _frame):
        logger.info("Received signal %d, shutting down", signum)
        shutdown.set()
        wake.set()

    def _sigusr1(_signum, _frame):
        wake.set()

    signal.signal(signal.SIGTERM, _sigterm)
    signal.signal(signal.SIGINT, _sigterm)
    signal.signal(signal.SIGUSR1, _sigusr1)


def _loop(interval, home, owner_pid, shutdown, wake):
    """Render until ``shutdown``; a set ``wake`` forces an early tick.

    Separated from signal installation so it can be driven with injected events
    in tests (no real signals, no main-thread requirement).
    """
    backoff = interval
    while not shutdown.is_set():
        try:
            n = render_once(home=home, owner_pid=owner_pid)
        except Exception:
            logger.exception("render_once failed")
            n = -1
        if n == 0:
            sleep_for = backoff
            backoff = min(MAX_BACKOFF, backoff * 2)
        else:
            backoff = interval
            sleep_for = interval
        wake.wait(timeout=sleep_for)
        wake.clear()
    logger.info("renderd stopped")


def run(interval=DEFAULT_INTERVAL, home=None):
    """Render loop: tick every ``interval`` s, exponential backoff with no tmux.

    SIGUSR1 forces an immediate tick — used by ``tmux-status-poke`` to close the
    cold-start gap on a fresh/``/clear``'d session; SIGTERM/SIGINT shut down.
    """
    owner_pid = os.getpid()
    shutdown = threading.Event()
    wake = threading.Event()
    _install_signal_handlers(shutdown, wake)
    _loop(interval, home, owner_pid, shutdown, wake)


def _parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="tmux-status render daemon: precompute per-pane status into a cache.",
    )
    p.add_argument(
        "--interval", type=int, default=DEFAULT_INTERVAL,
        help="Render interval in seconds (default: %(default)s)",
    )
    p.add_argument(
        "--once", action="store_true",
        help="Render a single pass and exit (testing / cache warm-up)",
    )
    p.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: %(default)s)",
    )
    args = p.parse_args(argv)
    if args.interval < 1:
        p.error("--interval must be at least 1 second")
    return args


def main():
    """Entry point for tmux-status-renderd."""
    args = _parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    _ensure_path()
    home = os.path.expanduser("~")

    if args.once:
        # A one-shot warm-up must survive a stray SIGUSR1: tmux-status-poke's
        # pkill fallback (``pkill -USR1 -f tmux-status-renderd``) and the tmux
        # re-source hooks can land a poke on this process mid-pass, and the
        # default SIGUSR1 disposition is to terminate — which would silently
        # abort the install cache warm-up. Ignore it (the daemon path installs
        # the real wake handler in run() instead).
        signal.signal(signal.SIGUSR1, signal.SIG_IGN)
        render_once(home=home)
        return

    lock_path = os.path.join(home, ".cache", "tmux-status", RENDER_DIRNAME, "renderd.lock")
    lock = acquire_singleton(lock_path)
    if lock is None:
        return
    logger.info("tmux-status-renderd starting (interval=%ds)", args.interval)
    run(interval=args.interval, home=home)
