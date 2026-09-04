# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A 3-line tmux status bar for Claude Code developers. Displays Claude session metadata (model, effort, context %, quota) on one combined line, filesystem path with git status, and a window tab bar — without touching keybindings or preferences.

## Development

The project is a collection of shell (bash), Python 3, and Node.js scripts installed via symlinks, plus a Python `server/` package (quota server + render daemon).

**Tests:** `make test` is the green gate (bash syntax + model unit tests + render-daemon unit tests + render pipeline integration). Per project policy the suite runs locally, not in GitHub Actions. `make test-server` runs the full `server/tests` suite (needs extra deps: `webtest`, `bottle`).

**Install locally:** `./install.sh` — symlinks scripts to `~/.local/bin/`, creates config at `~/.config/tmux-status/`, adds one `source-file` line to tmux.conf, configures the Claude Code statusLine hook.

**Reload after changes:** `tmux source-file ~/.config/tmux/tmux.conf` (or wherever the user's tmux.conf lives). `./install.sh` now does this automatically for a running server, so a `git pull` + reinstall can't leave the in-memory `status-format` stale.

**Uninstall:** `./uninstall.sh`

## Architecture

The system has independent data pipelines that feed into tmux's status bar rendering:

### Rendering (tmux calls *fork-free readers* every `status-interval`)

The status scripts are **thin readers**: all heavy work was moved into a background daemon (see below) so the tmux `#()` render path never forks (the historical cause of a status-bar fork-storm that pinned every core under load).

- **`overlay/status.conf`** — The only file sourced by the user's tmux.conf. Defines a 3-line status bar where lines 0–1 call shell scripts via `#(...)`, and line 2 is the relocated default tmux status format. Lines 0–1 all pass `#{pane_pid}`.
- **`scripts/tmux-claude-status`** (Bash) — Renders line 0 as ONE combined Claude line: model (effort) │ Ctx: bar pct% │ 5h │ 7d quota (the quota half is omitted when no key is configured). Takes only `<pane_pid>` (no mode arg). Sources the per-pane cache `~/.cache/tmux-status/render/pane-<pane_pid>.env` and `printf`s the line. Outputs nothing when the pane isn't running Claude or the cache is missing. Shows a dim `⋯` marker if the cache is older than `RENDER_MAX_STALE` (default 30s) — i.e. the daemon may be down. Does no process walking, transcript parsing, quota HTTP, or git.
- **`scripts/tmux-git-status`** (Bash) — Renders line 1 from the same per-pane cache's `GIT_LINE` (now keyed by `#{pane_pid}`, formerly `#{pane_current_path}`).
- **`scripts/tmux-status-apply-config`** (Bash) — Runs once on overlay source. Reads `settings.conf` to apply clock format and the optional top banner (`═╣ HOSTNAME · window-name ╠═` via `pane-border-format`; hostname is a precomputed static string, `#{window_name}` is a native tmux format).
- **`scripts/tmux-status-poke`** (Bash) — Wakes the daemon for one immediate tick by sending `SIGUSR1` to the pid in `renderd.lock` (falls back to `pkill -f tmux-status-renderd`). Invoked ONLY on infrequent events — tmux `set-hook` for `after-new-window`/`after-split-window`/`session-created`/`client-session-changed` (in `status.conf`, run with `run-shell -b`), and the context hook after it writes the bridge file. This closes the cold-start gap (blank Claude lines on a fresh or `/clear`'d session) without adding any fork to the per-render path. Always exits 0.

### Contract invariant (do not break)

The daemon writes the per-pane cache keyed by **pid** (`pane-<pid>.env`); every reader invocation in `overlay/status.conf` MUST pass `#{pane_pid}`. Passing `#{pane_current_path}` (the pre-refactor git-line argument) makes the reader build a bogus cache path and silently blank that line. `tests/unit/test_status_conf_contract.sh` gates this. Because the scripts are symlinks (live-updated by `git pull`) but tmux's `status-format` is in-memory until re-sourced, `install.sh` re-sources a running server so the live config can't drift from the scripts.

### File-descriptor budget invariant (do not break)

The fork-free refactor moved heavy work off the render path, but tmux still spawns each `#()` reader by `fork()`+`socketpair()` **inside the tmux server process** — so every status line costs one *server* fd per redraw, and re-forks **once per attached client** each `status-interval`. The server's fd budget is shared with one fd per attached client, and macOS's launchd default soft `RLIMIT_NOFILE` is only **256**. Long-lived clients (abandoned mosh/SSH reconnects) accumulate and cause two failures: (a) fd exhaustion — a redraw can't get a socketpair, so tmux prints `<'…' didn't start>` for the `#()` lines (RCA: `.rca/tmux-status-didnt-start-fd-exhaustion/`); and (b) a **fork storm** — N stale clients = an N× reader fork rate, which has driven a 10-core Mac's load average to ~100 (see memory `moshtail-mosh-orphan-forkstorm`; upstream cause is Moshtail spawning a new `mosh-server` per iOS cold-relaunch without reaping the old one). Implications when changing the render path: keep the per-pane `#()` job count low (do **not** add status lines casually), `tmux-status-session` raises `ulimit -n` before creating a server, and `install.sh` warns when a running server's soft limit is low. A pane shell's `ulimit -n` may be `.zshrc`-inflated — read the server's real limit via `tmux run-shell 'ulimit -Sn'`.

**Client-accumulation guardrails (do not remove):** `tmux-status-prune-clients` detaches clients idle past a threshold; `--reap-transport` also kills each detached client's backing `mosh-server`/`sshd-session` (allowlisted — a local terminal's emulator/`login` is never reaped; only idle-past-threshold clients, so the active session is always safe). It runs three ways: on demand, event-driven via the `client-attached` `set-hook` in `overlay/status.conf` (prunes on every new attach — self-limits the pile-up), and as a periodic backstop (launchd agent `io.mikey.tmux-status-prune` / systemd `tmux-status-prune.timer`, every ~30m, idle 2h). The prune script prepends Homebrew/local dirs to `PATH` (mirrors `render.py`'s `_EXTRA_PATH`) so `tmux` resolves under launchd/cron's minimal PATH.

### Status pre-computation (`tmux-status-renderd` daemon)

- **`server/tmux_status_server/render.py`** (Python) — The render daemon. On its own cadence (`--interval`, default 5s) it takes ONE `ps -axo pid=,ppid=` snapshot, enumerates panes via `tmux list-panes -a`, resolves each pane→Claude-session in-memory, parses transcripts, fetches/reads quota, computes git status, and writes one shell-sourceable cache file per pane (`pane-<pid>.env`) plus pruning panes that closed. Identity is keyed on the **live session file** (`~/.claude/sessions/<pid>.json`), whose `sessionId` is rewritten in place on `/clear`: that id locates the exact transcript (`<sessionId>.jsonl`) and the exact context bridge. The model is the transcript's once it has an assistant reply, otherwise the bridge's `model` — so a fresh/`/clear`'d session (whose new transcript has no assistant message yet) renders immediately instead of blanking the Claude line until work starts. **Effort precedence: the bridge's live `effort` (written by the statusLine hook from `effort.level`, reflecting mid-session Shift+Tab changes) → the transcript's last `/effort` echo → `~/.claude/settings.json` `effortLevel` → `auto`.** The transcript's absence is tolerated. Installed as the `tmux-status-renderd` entry point; runs as a launchd agent / systemd user unit with auto-restart. A `flock` singleton (`singleton.py`) guarantees one instance. `--once` renders a single pass (used for tests and install cache warm-up). `model.py` is a vendored byte-identical copy of `scripts/tmux_claude_model.py` (a drift test enforces this).

### Context Window Tracking (real-time, via Claude Code hook)

- **`scripts/tmux-status-context-hook.js`** (Node.js) — A Claude Code `statusLine` hook. Receives JSON on stdin with `session_id`, `model.id`, `context_window`, and the live `effort.level` / `thinking.enabled`, normalizes autocompact (16.5% reserved buffer), and writes atomic JSON `{used_pct, model, effort, thinking, timestamp}` to `~/.cache/tmux-status/claude-ctx-{sessionId}.json`, then pokes the daemon. Carrying `model` lets the daemon render a fresh/`/clear`'d session before any assistant reply; carrying `effort` is what makes the bar track the header's live effort (incl. mid-session Shift+Tab changes) instead of a frozen `/effort` transcript echo. To avoid waste it reads the prior bridge and skips the write+poke when `used_pct`, `model`, `effort`, and `thinking` are all unchanged; a new/cleared session has no prior file, so it always writes and pokes (guaranteeing the cold-start nudge).

### Quota Fetching (HTTP server + client)

- **`server/tmux_status_server/cli_usage.py`** (Python) — The usage collector. Boots the `claude` CLI headless in a **dedicated tmux socket**, sends `/usage`, captures the pane, and parses the three usage windows (`Current session` → `five_hour`, `Current week (all models)` → `seven_day`, `Current week (<model>)` → `model_week`, stored but not rendered). Uses `--ax-screen-reader`, which renders flat labelled text instead of the boxed TUI and is far more stable to parse. `UsageScreenParser` is pure (`str -> ParsedUsage`), so all parsing is tested offline against golden fixtures in `server/tests/fixtures/`. Reset times arrive as human strings (`3:50pm`, `Sep 3 at 9am`) and are resolved to the next future occurrence as **ISO 8601**, which is what `render.py`'s `fmt_reset()` parses. Failures return a bridge with `status: "error"` and a specific code (`cli_not_found`, `cli_boot_timeout`, `cli_not_authenticated`, `cli_workspace_untrusted`, `usage_screen_timeout`, `usage_no_limit_windows`, `usage_parse_failed`, `tmux_unavailable`, `collector_crashed`), so a future CLI layout change is diagnosable from logs.
- **`server/tmux_status_server/`** (Python package) — HTTP server that runs the collector on a background poll thread at a configurable interval (default 300s). Serves `/quota` and `/health` endpoints. Supports optional API key auth via `--api-key-file`. Installed as `tmux-status-server` entry point. Runs as a systemd user unit (Linux) or launchd agent (macOS), bound to `127.0.0.1:7850` by default.
- **Client fetch in `render.py`** — The render daemon's `_maybe_fetch_quota()` fetches from `QUOTA_SOURCE` (default `http://127.0.0.1:7850`) once per tick, validates JSON, and writes an atomic disk cache at `~/.cache/tmux-status/claude-quota.json`. Supports `QUOTA_API_KEY` header and `QUOTA_CACHE_TTL` for remote servers. Falls back to stale cache on failure. (This logic moved out of `tmux-claude-status` when it became a thin reader.)

**No credential is copied into tmux-status.** Usage is read from the already-authenticated CLI. The former claude.ai session key (`claude-usage-key.json`) and the `curl_cffi` scraper were removed: the key was revoked server-side on any browser logout or re-auth while `expiresAt` still claimed weeks of validity, which surfaced as `403 account_session_invalid` and an `X` in the status bar.

### Usage-capture isolation invariant (do not break)

The headless capture session MUST run on a **dedicated tmux socket** (`tmux -L tmux-status-usage`), never the user's default server. On the default server it would (a) be enumerated by `render.py`'s `tmux list-panes -a` and get a bogus `pane-<pid>.env`, (b) consume tmux-server fds against the 256 soft limit documented above, and (c) be detached and transport-reaped by `tmux-status-prune-clients`. `config.py` rejects `--usage-socket default` to enforce this at the CLI boundary.

**Working-directory contract:** the daemon inherits launchd's cwd (`/`), which the CLI treats as untrusted — it shows a workspace-trust prompt and never becomes ready. `default_usage_cwd()` therefore picks a directory the user has already accepted (`~/.claude.json` → `projects[dir].hasTrustDialogAccepted`), restricted to dirs this user owns that are **not world-writable**: the CLI reads `CLAUDE.md` and settings from its cwd, so a world-writable one (`/tmp`) is an instruction-injection surface. Falls back to `$HOME`. Override with `--usage-cwd`. The trust prompt is detected and reported as `cli_workspace_untrusted`, never auto-answered — trusting a directory is the user's security decision.

**PATH contract:** launchd/systemd export neither `/opt/homebrew/bin` (tmux) nor `~/.local/bin` (claude). `search_path()` augments PATH for both the `which()` lookups and the subprocess env, without mutating `os.environ` (the collector runs on the poll thread). Mirrors `render.py`'s `_EXTRA_PATH`.

**Authentication contract:** quota is a subscription measurement. The pane command uses `/usr/bin/env -u` to remove documented alternate-provider and explicit-credential overrides after the pane shell has sourced startup files; scrubbing only the daemon environment is insufficient because `.zshenv` can re-export them. Preserve `CLAUDE_CONFIG_DIR` and routing variables so the user's selected login store and network path remain intact. `--usage-inherit-auth-env` is the explicit opt-out. A settings-file `apiKeyHelper` cannot be removed through the environment, so an opened Usage dialog without subscription windows must report `usage_no_limit_windows`.

Two further contracts in `cli_usage.py`:
- **Geometry is fixed at 120x45.** Wrapping width decides where lines break, and therefore whether the golden fixtures still match.
- **Readiness is keyed on the input-mode footer (`shift+tab`), never the startup banner.** Measured: the banner paints ~3s before the input box accepts keystrokes, and keys sent in that window are silently dropped. The transient `effort:` hint is also unusable — it clears after ~10s.

### Session Launcher (optional)

- **`scripts/tmux-status-session`** (Bash/Python) — Data-driven tmux session creator. Reads `~/.config/tmux-status/windows.json` to create named windows with staggered command execution. Re-attaches if the session already exists.

## Key File Locations (at runtime)

| Path | Purpose |
|------|---------|
| `~/.config/tmux-status/settings.conf` | User settings (clock, banner, quota source) |
| `~/.config/tmux-status/windows.json` | Session launcher config |
| `~/.cache/tmux-status/claude-ctx-*.json` | Context/effort bridge files (`used_pct`, `model`, live `effort`/`thinking` — written by hook) |
| `~/.cache/tmux-status/claude-quota.json` | Quota cache (written by renderer from server response) |
| `~/.cache/tmux-status/render/pane-<pid>.env` | Per-pane render cache (written by the daemon, sourced by the thin readers) |
| `~/.cache/tmux-status/render/renderd.lock` | Render daemon `flock` singleton guard; first line is the daemon pid (read by `tmux-status-poke`) |

## Conventions

- **Atomic writes**: All bridge/cache files use temp-file + rename to avoid partial reads.
- **Silent failure**: Scripts exit 0 and output nothing when data is unavailable (no Claude running, no quota key, etc.).
- **Color palette**: 256-color codes throughout. Gradient bars shift blue→green→yellow→orange→red as usage increases. Segment labels use a fixed pastel palette (see README for reference table).
- **tmux string formatting**: Lines 0–1 use `#(script args)` shell expansion. Line 2 is the verbatim default tmux status format template relocated from `status-format[0]`.

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
