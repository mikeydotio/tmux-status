# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [v3.0.0] - 2026-09-04

### Breaking
- Quota is now measured by driving the authenticated `claude` CLI headlessly;
  the claude.ai session-key scraper (`claude-usage-key.json`, `curl_cffi`) is
  gone (395b6c2). **Upgraders must have a logged-in `claude` CLI** — the key
  was silently revoked server-side on any browser logout, surfacing as
  `403 account_session_invalid`. No credential is copied into tmux-status.

### Added
- Usage collector that boots the Claude CLI in a dedicated headless tmux
  socket, sends `/usage`, and parses the limit windows offline (7405495)

### Fixed
- Identify missing quota windows instead of failing opaquely (8220f44)
- Isolate quota-capture authentication from alternate-provider env overrides
  (bff4391)
- Start the capture in a trusted, non-world-writable cwd (6933e21)
- Resolve `tmux`/`claude` under launchd's minimal PATH (837826d)
- Publish the renderd PID without holding flock (7221dd8)
- Protect every server entry point from SIGUSR1; remove the unsafe renderd
  signal broadcast (ff94b32, cf3292e, 9682258)
- Persist launch-agent diagnostics (95c81ba)
- Rebuild and uninstall the server package from clean/managed environments
  (7bd7987, 584ddde)
- Correct the server package description (4e72b7b)
- Never block a non-interactive install on the key prompt (5cdbfd2)

### Documentation
- Document CLI usage collection; retire the session key in install (20d7af8)
- Link CLAUDE.md from AGENTS.md; ignore the dispatch sentinel (78aff33)

### Testing
- Close the collector source fixture (1c81c6c)

### Maintenance
- Ignore `.codex/` per-story worktrees (94b8f24)

_[manual]_

## [Unreleased]

## [v2.7.0] - 2026-08-23

### Fixed
- Keep Codex status stable when one long-lived process retains multiple root
  rollouts and metadata-linked subagents: select by root-thread activity, ignore
  child-only writes, restore sticky choices after daemon restarts, and preserve
  visibly stale last-known-good status when activity evidence is ambiguous.

_[manual]_

## [v2.6.0] - 2026-08-19

### Added
- Add first-class Codex model, effort, context, quota, and window-name support
  through exact local rollout discovery.
- Add the provider-neutral `tmux-agent-status` reader while retaining
  `tmux-claude-status` as a compatibility alias.

### Changed
- Normalize the render cache for Claude Code and Codex without adding work to
  the fork-free tmux reader path.

### Fixed
- Show Codex quota reset countdowns without repeating the window duration.
- Prefer the freshest general Codex account quota across exact active rollouts
  instead of an inactive model-specific zero-usage snapshot.

_[manual]_

## [v2.5.3] - 2026-07-05

### Documentation
- note bottle as a make test-server dependency (6f85623)

_[manual]_

## [v2.5.2] - 2026-07-05

### Testing
- expect the 7 current SCRIPTS entries (b1a5056)

_[manual]_

## [v2.5.1] - 2026-07-05

### Changed
- bracket tabs colored to match name, drop status-left hostname (3d18e25)

_[manual]_

## [v2.5.0] - 2026-07-05

### Added
- show current window name in the top banner (56b7e8f)

### Changed
- one Claude line, no cost, live effort (a85e9a1)

### Documentation
- 3-line layout, live effort, window-name banner (271253e)

### Testing
- add live integration test proving hooks can't hijack a pane (6e09734)

_[manual]_

## [v2.4.1] - 2026-07-03

### Fixed
- silence background hooks so run-shell output can't blank panes (bcc168d)

_[manual]_

## [v2.4.0] - 2026-07-03

### Added
- auto-reap abandoned mosh/SSH clients to prevent fork storms (e7c5ee2)

_[manual]_

## [v2.3.5] - 2026-06-24

### Added
- fix "didn't start" status lines from tmux-server fd exhaustion (a4489c2)

### Documentation
- document fd-exhaustion root cause, troubleshooting, and invariant (248385d)

_[manual]_

## [v2.3.4] - 2026-06-23

### Fixed
- precompute hostname so the top banner can't fork (ed681ab)

_[manual]_

## [v2.3.3] - 2026-06-19

### Fixed
- install from the script's own checkout, not a stale clone (86be61b)

_[manual]_

## [v2.3.2] - 2026-06-18

### Fixed
- render Claude lines on fresh/cleared sessions without priming (281ca1a)
- probe the tmux server without the info() name clash (8f10f7a)

### Maintenance
- remove the test-only GitHub Actions workflow (0523c30)

_[manual]_

## [v2.3.1] - 2026-06-18

### Fixed
- restore git line and close cold-start blank after fork-free refactor (ffd03f4)
- harden PATH so the daemon finds tmux/git under launchd (b7e530d)

### Documentation
- document the daemon poke/wake and reader-contract invariant (805a86d)

### Testing
- avoid SC2088 in integration test git assertion (de4a3f0)

_[manual]_

## [v2.3.0] - 2026-06-17

### Changed
- Eliminate the status-bar fork-storm. All heavy per-pane work (process-tree walk, transcript parsing, quota HTTP, daily-cost scan, git status) moved out of the tmux `#()` render path into a new background render daemon. The status scripts are now fork-free cache readers, so the render path can no longer pile up and pin every CPU core under load. Status-bar output is byte-for-byte unchanged.
- `tmux-git-status` now takes `#{pane_pid}` (was `#{pane_current_path}`) so it can share the per-pane cache.
- `tmux_claude_model.py` is no longer symlinked into `~/.local/bin` — the thin readers don't import it and the daemon vendors its own copy.

### Added
- `tmux-status-renderd` render daemon (`server/tmux_status_server/render.py`): one `ps` snapshot per tick, in-memory pane→session resolution, per-pane `.env` cache, `flock` singleton guard, launchd/systemd auto-restart, and a `--once` one-shot mode (used for tests and install cache warm-up).
- Per-pane render cache at `~/.cache/tmux-status/render/pane-<pid>.env`, plus a dim `⋯` staleness marker on the model line when the daemon hasn't refreshed within `RENDER_MAX_STALE` (default 30s).
- `make test` green gate: render-daemon unit tests, `flock`/deploy tests, and a render-pipeline integration test that asserts the readers do no heavy work even when the daemon is down.

_[manual]_

## [v2.2.1] - 2026-06-03

### Fixed
- keep context % and quota visible when a session idles (0083f99)

_[manual]_

## [v2.2.0] - 2026-05-26

### Added
- show yellow [cmd] chip when tmux prefix is armed (544f4e0)

### Fixed
- remove apostrophe that broke bash parse of embedded heredoc (e5ce852)
- display "5h" instead of "?" when no active session, "X" for errors (f44b2f2)

### Testing
- add bash -n syntax gate and GitHub Actions workflow (6e56776)

### Maintenance
- bump actions/checkout to v5 and actions/setup-python to v6 for Node 24 (7d92c70)
- untrack transient .claude/worktrees gitlinks and ignore them (dd18f1a)
- fix shellcheck warnings and switch python tests to stdlib unittest (ab68f0e)

_[manual]_

## [v2.1.2] - 2026-04-09

_[force]_

## [v2.1.1] - 2026-04-08

### Maintenance
- track tool config (.storyhook, .semver, .planning) (117a2bf)

_[manual]_

## [v2.1.0] - 2026-04-07

### Added
- add token cost tracking and split status into 4-line layout (2268633)

_[manual]_

## [v2.0.0] - 2026-04-07

### Added
- add --server flag to install.sh for network quota serving (b61381c)

_[manual]_

## [v1.2.0] - 2026-04-06

### Documentation
- document client/server quota mode and update stale daemon references (fe9a9ab)

_[manual]_

## [v1.1.0] - 2026-04-06

_[force]_

## [v1.0.0] - 2026-04-06

- Initial version tracking

_[manual]_
