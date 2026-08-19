# Codex-Compatible Agent Status Design

## Goal

Add first-class Codex status to line 0 while preserving Claude Code behavior and
the existing single-reader, fork-free tmux render path.

## Architecture

`tmux-status-renderd` remains the only component allowed to inspect processes,
read session files, parse JSONL, fetch Claude quota, or invoke `git`. Once per
tick it takes one process snapshot, identifies Claude and Codex descendants of
each tmux pane, selects the candidate nearest the pane process, and uses the
newest process start time to break equal-depth ties.

Claude continues to use its live session file, exact transcript, status-line
bridge, and optional Claude quota server. Codex uses the exact rollout JSONL
that the selected Codex process currently has open. Linux resolves that file
through `/proc/<pid>/fd`; macOS takes one batched `lsof` snapshot for all
selected Codex PIDs. Multiple or missing open rollout files are ambiguous and
produce no Codex status; the daemon never guesses from filenames or mtimes.

Both provider adapters produce the same normalized record:

- provider, raw/short model, effort, optional thinking flag, and optional
  context percentage;
- zero, one, or two quota slots with a duration label, reset countdown, and
  used percentage;
- quota health metadata used only for existing error coloring.

The daemon serializes that record as shell-quoted `AGENT_*` fields in the
existing atomic per-pane cache beside the isolated `GIT_LINE` and `RENDER_TS`.
`tmux-agent-status` only sources that cache and formats it. The legacy
`tmux-claude-status` name sources the same reader for compatibility with old
installations and already-loaded tmux configurations.

## Codex Data Mapping

The parser scans the rollout tail in reverse, growing the tail window only when
needed, and independently keeps the newest valid `turn_context`, `task_started`,
and `token_count` records.
Malformed, truncated, non-object, or partially populated records are ignored.

- `turn_context.payload.model` and `.effort` supply model and reasoning effort.
- `task_started.payload.model_context_window` supplies context capacity.
- `token_count.payload.info.last_token_usage.total_tokens` supplies used
  context. The displayed percentage is rounded and clamped to 0–100.
- `token_count.payload.rate_limits.primary` and `.secondary` become optional
  quota slots. `window_minutes` becomes a compact duration (`5h`, `7d`),
  `used_percent` is rounded and clamped, and Unix `resets_at` becomes the same
  compact countdown style used elsewhere (`40m`, `3.2h`, `5.1d`).

Missing model, effort, context, or quota data omits only that display segment.
Codex quota is rendered as `<duration>/<countdown>: <bar> <percent>`. Claude's
current model/effort/context/quota output remains unchanged.

## Configuration and Compatibility

`CODEX_HOME` may be set in `~/.config/tmux-status/settings.conf`. If absent,
the daemon's `CODEX_HOME` environment variable is used, then `~/.codex`.
The installer does not modify Codex configuration or install Codex hooks.

The new overlay invokes `tmux-agent-status`; `tmux-claude-status` remains
installed as a compatibility alias. Automatic naming recognizes both `claude`
and `codex`, using the existing `✧` marker without a provider badge on line 0.

## Error Handling and Safety

All process, descriptor, JSON, and filesystem failures are local to the
affected pane or metric. Cache writes remain atomic, dead-pane caches are
pruned, stale cache markers remain available, and non-agent panes continue to
write only git/freshness fields. Codex data is never sent to the Claude quota
server, and no OpenAI or Anthropic API calls are added.

## Verification

Unit fixtures cover process selection, Linux/macOS descriptor resolution,
rollout parsing, context math, quota conversion, model formatting, and safe
failure. Shell and integration tests cover both reader names, Claude regression
output, Codex output, stale/non-agent behavior, installer and overlay contracts,
automatic naming, and the no-heavy-work reader invariant. The release gate is
`make test` followed by `make test-server`.
