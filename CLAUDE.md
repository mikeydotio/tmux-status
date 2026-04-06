# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A 3-line tmux status bar for Claude Code developers. Displays Claude session metadata (model, effort, context %, quota), filesystem path with git status, and a window tab bar — without touching keybindings or preferences.

## Development

There is no build system, test suite, or linter. The project is a collection of shell (bash), Python 3, and Node.js scripts installed via symlinks.

**Install locally:** `./install.sh` — symlinks scripts to `~/.local/bin/`, creates config at `~/.config/tmux-status/`, adds one `source-file` line to tmux.conf, configures the Claude Code statusLine hook.

**Reload after changes:** `tmux source-file ~/.config/tmux/tmux.conf` (or wherever the user's tmux.conf lives).

**Uninstall:** `./uninstall.sh`

## Architecture

The system has three independent data pipelines that feed into tmux's status bar rendering:

### Rendering (tmux calls scripts every 5s via `status-interval`)

- **`overlay/status.conf`** — The only file sourced by the user's tmux.conf. Defines a 3-line status bar where lines 0 and 1 call shell scripts via `#(...)`, and line 2 is the relocated default tmux status format.
- **`scripts/tmux-claude-status`** (Bash/Python) — Renders line 0. Walks the process tree from `#{pane_pid}` to find a Claude process, reads the session `.jsonl` transcript (last 512KB, reverse) for model/effort, reads bridge files for context % and quota. Outputs nothing when the pane isn't running Claude.
- **`scripts/tmux-git-status`** (Bash) — Renders line 1. Takes `#{pane_current_path}`, collapses `$HOME` to `~`, shows branch name, dirty/clean state, ahead/behind counts.
- **`scripts/tmux-status-apply-config`** (Bash) — Runs once on overlay source. Reads `settings.conf` to apply clock format and optional top hostname banner.

### Context Window Tracking (real-time, via Claude Code hook)

- **`scripts/tmux-status-context-hook.js`** (Node.js) — A Claude Code `statusLine` hook. Receives JSON on stdin with `session_id` and `context_window` data, normalizes autocompact (16.5% reserved buffer), writes atomic JSON to `~/.cache/tmux-status/claude-ctx-{sessionId}.json`.

### Quota Fetching (HTTP server + client)

- **`server/tmux_status_server/`** (Python package) — HTTP server that scrapes claude.ai for quota data using `curl_cffi` (Chrome TLS fingerprint). Runs a background poll thread at a configurable interval (default 300s). Serves `/quota` and `/health` endpoints. Supports optional API key auth via `--api-key-file`. Installed as `tmux-status-server` entry point. Runs as a systemd user unit (Linux) or launchd agent (macOS), bound to `127.0.0.1:7850` by default.
- **Client mode in `scripts/tmux-claude-status`** — The renderer's `_maybe_fetch_quota()` function fetches from `QUOTA_SOURCE` (default `http://127.0.0.1:7850`), validates JSON, and writes an atomic disk cache at `~/.cache/tmux-status/claude-quota.json`. Supports `QUOTA_API_KEY` header and `QUOTA_CACHE_TTL` for remote servers. Falls back to stale cache on failure.

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

## Conventions

- **Atomic writes**: All bridge/cache files use temp-file + rename to avoid partial reads.
- **Silent failure**: Scripts exit 0 and output nothing when data is unavailable (no Claude running, no quota key, etc.).
- **Color palette**: 256-color codes throughout. Gradient bars shift blue→green→yellow→orange→red as usage increases. Segment labels use a fixed pastel palette (see README for reference table).
- **tmux string formatting**: Line 0 and 1 use `#(script args)` shell expansion. Line 2 is the verbatim default tmux status format template relocated from `status-format[0]`.

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
