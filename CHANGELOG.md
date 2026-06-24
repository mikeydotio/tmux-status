# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/).

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
