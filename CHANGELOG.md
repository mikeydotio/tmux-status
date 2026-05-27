# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/).

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
