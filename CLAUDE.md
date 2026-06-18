# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A 4-line tmux status bar for Claude Code developers. Displays Claude session metadata (model, effort, context %, quota, token cost), filesystem path with git status, and a window tab bar — without touching keybindings or preferences.

## Development

The project is a collection of shell (bash), Python 3, and Node.js scripts installed via symlinks, plus a Python `server/` package (quota server + render daemon).

**Tests:** `make test` is the green gate (bash syntax + model unit tests + render-daemon unit tests + render pipeline integration). Per project policy the suite runs locally, not in GitHub Actions. `make test-server` runs the full `server/tests` suite (needs extra deps: `webtest`, `curl_cffi`).

**Install locally:** `./install.sh` — symlinks scripts to `~/.local/bin/`, creates config at `~/.config/tmux-status/`, adds one `source-file` line to tmux.conf, configures the Claude Code statusLine hook.

**Reload after changes:** `tmux source-file ~/.config/tmux/tmux.conf` (or wherever the user's tmux.conf lives). `./install.sh` now does this automatically for a running server, so a `git pull` + reinstall can't leave the in-memory `status-format` stale.

**Uninstall:** `./uninstall.sh`

## Architecture

The system has independent data pipelines that feed into tmux's status bar rendering:

### Rendering (tmux calls *fork-free readers* every `status-interval`)

The status scripts are **thin readers**: all heavy work was moved into a background daemon (see below) so the tmux `#()` render path never forks (the historical cause of a status-bar fork-storm that pinned every core under load).

- **`overlay/status.conf`** — The only file sourced by the user's tmux.conf. Defines a 4-line status bar where lines 0–2 call shell scripts via `#(...)`, and line 3 is the relocated default tmux status format. Lines 0–2 all pass `#{pane_pid}`.
- **`scripts/tmux-claude-status`** (Bash) — Renders lines 0 and 1 (`model` / `quota` mode). Sources the per-pane cache `~/.cache/tmux-status/render/pane-<pane_pid>.env` and `printf`s the line (same `bar_char`/colors as before). Outputs nothing when the pane isn't running Claude or the cache is missing. Shows a dim `⋯` marker if the cache is older than `RENDER_MAX_STALE` (default 30s) — i.e. the daemon may be down. Does no process walking, transcript parsing, quota HTTP, or git.
- **`scripts/tmux-git-status`** (Bash) — Renders line 2 from the same per-pane cache's `GIT_LINE` (now keyed by `#{pane_pid}`, formerly `#{pane_current_path}`).
- **`scripts/tmux-status-apply-config`** (Bash) — Runs once on overlay source. Reads `settings.conf` to apply clock format and optional top hostname banner.
- **`scripts/tmux-status-poke`** (Bash) — Wakes the daemon for one immediate tick by sending `SIGUSR1` to the pid in `renderd.lock` (falls back to `pkill -f tmux-status-renderd`). Invoked ONLY on infrequent events — tmux `set-hook` for `after-new-window`/`after-split-window`/`session-created`/`client-session-changed` (in `status.conf`, run with `run-shell -b`), and the context hook after it writes the bridge file. This closes the cold-start gap (blank Claude lines on a fresh or `/clear`'d session) without adding any fork to the per-render path. Always exits 0.

### Contract invariant (do not break)

The daemon writes the per-pane cache keyed by **pid** (`pane-<pid>.env`); every reader invocation in `overlay/status.conf` MUST pass `#{pane_pid}`. Passing `#{pane_current_path}` (the pre-refactor git-line argument) makes the reader build a bogus cache path and silently blank that line. `tests/unit/test_status_conf_contract.sh` gates this. Because the scripts are symlinks (live-updated by `git pull`) but tmux's `status-format` is in-memory until re-sourced, `install.sh` re-sources a running server so the live config can't drift from the scripts.

### Status pre-computation (`tmux-status-renderd` daemon)

- **`server/tmux_status_server/render.py`** (Python) — The render daemon. On its own cadence (`--interval`, default 5s) it takes ONE `ps -axo pid=,ppid=` snapshot, enumerates panes via `tmux list-panes -a`, resolves each pane→Claude-session in-memory, parses transcripts, fetches/reads quota, computes session+daily cost, computes git status, and writes one shell-sourceable cache file per pane (`pane-<pid>.env`) plus pruning panes that closed. The `.env` contract is the exact `KEY=value` set the old `tmux-claude-status` heredoc emitted, so reader output is byte-for-byte unchanged. Installed as the `tmux-status-renderd` entry point; runs as a launchd agent / systemd user unit with auto-restart. A `flock` singleton (`singleton.py`) guarantees one instance. `--once` renders a single pass (used for tests and install cache warm-up). `model.py` is a vendored byte-identical copy of `scripts/tmux_claude_model.py` (a drift test enforces this).

### Context Window Tracking (real-time, via Claude Code hook)

- **`scripts/tmux-status-context-hook.js`** (Node.js) — A Claude Code `statusLine` hook. Receives JSON on stdin with `session_id` and `context_window` data, normalizes autocompact (16.5% reserved buffer), writes atomic JSON to `~/.cache/tmux-status/claude-ctx-{sessionId}.json`.

### Quota Fetching (HTTP server + client)

- **`server/tmux_status_server/`** (Python package) — HTTP server that scrapes claude.ai for quota data using `curl_cffi` (Chrome TLS fingerprint). Runs a background poll thread at a configurable interval (default 300s). Serves `/quota` and `/health` endpoints. Supports optional API key auth via `--api-key-file`. Installed as `tmux-status-server` entry point. Runs as a systemd user unit (Linux) or launchd agent (macOS), bound to `127.0.0.1:7850` by default.
- **Client fetch in `render.py`** — The render daemon's `_maybe_fetch_quota()` fetches from `QUOTA_SOURCE` (default `http://127.0.0.1:7850`) once per tick, validates JSON, and writes an atomic disk cache at `~/.cache/tmux-status/claude-quota.json`. Supports `QUOTA_API_KEY` header and `QUOTA_CACHE_TTL` for remote servers. Falls back to stale cache on failure. (This logic moved out of `tmux-claude-status` when it became a thin reader.)

### Session Launcher (optional)

- **`scripts/tmux-status-session`** (Bash/Python) — Data-driven tmux session creator. Reads `~/.config/tmux-status/windows.json` to create named windows with staggered command execution. Re-attaches if the session already exists.

## Key File Locations (at runtime)

| Path | Purpose |
|------|---------|
| `~/.config/tmux-status/settings.conf` | User settings (clock, banner, quota source) |
| `~/.config/tmux-status/windows.json` | Session launcher config |
| `~/.config/tmux-status/claude-usage-key.json` | Session key for quota API |
| `~/.cache/tmux-status/claude-ctx-*.json` | Context bridge files (written by hook) |
| `~/.cache/tmux-status/claude-quota.json` | Quota cache (written by renderer from server response) |
| `~/.cache/tmux-status/claude-daily-cost.json` | Daily token cost cache (60s TTL, recomputed from all today's JSONLs) |
| `~/.cache/tmux-status/render/pane-<pid>.env` | Per-pane render cache (written by the daemon, sourced by the thin readers) |
| `~/.cache/tmux-status/render/renderd.lock` | Render daemon `flock` singleton guard; first line is the daemon pid (read by `tmux-status-poke`) |

## Conventions

- **Atomic writes**: All bridge/cache files use temp-file + rename to avoid partial reads.
- **Silent failure**: Scripts exit 0 and output nothing when data is unavailable (no Claude running, no quota key, etc.).
- **Color palette**: 256-color codes throughout. Gradient bars shift blue→green→yellow→orange→red as usage increases. Segment labels use a fixed pastel palette (see README for reference table).
- **tmux string formatting**: Lines 0–2 use `#(script args)` shell expansion. Line 3 is the verbatim default tmux status format template relocated from `status-format[0]`.

## Task Tracking

This project uses **storyhook** (`story` CLI) with prefix `TS`. The `.storyhook/` directory is version-controlled — do not gitignore it. See `AGENTS.md` for the full workflow.

<!-- semver:start -->
## Semantic Versioning

This project uses semantic versioning managed by the `/semver` plugin.

### Version Awareness
- Read the `VERSION` file at the start of each conversation to know the current version.
- Read `.semver/config.yaml` to understand the versioning configuration.
- When discussing releases, deployments, or changes, reference the current version.

### Commit Discipline
- Write meaningful, descriptive commit messages. Each commit message may appear in an auto-generated changelog.
- Use conventional-commit-style prefixes when they fit naturally: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`.
- The first line of the commit message should be a concise summary (under 72 characters). Add detail in the body if needed.

### Version Bump Guidance
When recommending or performing a version bump:
- **patch** (0.0.x): Bug fixes, documentation corrections, minor refactors with no behavior change.
- **minor** (0.x.0): New features, new capabilities, non-breaking additions to the public API or user-facing behavior.
- **major** (x.0.0): Breaking changes — removed features, changed interfaces, incompatible API modifications, behavior changes that require consumers to update.

When you notice the user has completed a logical unit of work, suggest running `/semver bump` with the appropriate level.

### Hooks
- Custom pre-bump and post-bump hooks can be added in `.semver/hooks/`.
- Never trigger `/semver bump` from within a hook — this causes infinite recursion.

### Configuration
Versioning settings are in `.semver/config.yaml`. Do not modify this file unless the user explicitly asks to change semver settings.
<!-- semver:end -->
