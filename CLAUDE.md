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

### Quota Fetching (optional background daemon)

- **`scripts/tmux-status-quota-poll`** (Python) — Background daemon that calls `tmux-status-quota-fetch` at intervals (configurable via `QUOTA_REFRESH_PERIOD` in `settings.conf`; `0` disables polling). Handles SIGUSR1 (immediate fetch), SIGTERM/SIGINT (clean shutdown).
- **`scripts/tmux-status-quota-fetch`** (Python) — Fetches 5-hour and 7-day API quota from claude.ai using `curl_cffi` (Chrome TLS impersonation to bypass Cloudflare). Reads session key from `~/.config/tmux-status/claude-usage-key.json`. Writes atomic JSON to the quota bridge file (configurable via `QUOTA_DATA_PATH` in `settings.conf`, default `~/.cache/tmux-status/claude-quota.json`).

### Session Launcher (optional)

- **`scripts/tmux-status-session`** (Bash/Python) — Data-driven tmux session creator. Reads `~/.config/tmux-status/windows.json` to create named windows with staggered command execution. Re-attaches if the session already exists.

## Key File Locations (at runtime)

| Path | Purpose |
|------|---------|
| `~/.config/tmux-status/settings.conf` | User settings (clock, banner, quota interval) |
| `~/.config/tmux-status/windows.json` | Session launcher config |
| `~/.config/tmux-status/claude-usage-key.json` | Session key for quota API |
| `~/.cache/tmux-status/claude-ctx-*.json` | Context bridge files (written by hook) |
| `~/.cache/tmux-status/claude-quota.json` | Quota cache — default, configurable via `QUOTA_DATA_PATH` |

## Conventions

- **Atomic writes**: All bridge/cache files use temp-file + rename to avoid partial reads.
- **Silent failure**: Scripts exit 0 and output nothing when data is unavailable (no Claude running, no quota key, etc.).
- **Color palette**: 256-color codes throughout. Gradient bars shift blue→green→yellow→orange→red as usage increases. Segment labels use a fixed pastel palette (see README for reference table).
- **tmux string formatting**: Line 0 and 1 use `#(script args)` shell expansion. Line 2 is the verbatim default tmux status format template relocated from `status-format[0]`.

## Task Tracking

This project uses **storyhook** (`story` CLI) with prefix `TS`. The `.storyhook/` directory is version-controlled — do not gitignore it. See `AGENTS.md` for the full workflow.
