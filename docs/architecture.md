# Architecture

tmux-status keeps tmux's frequently refreshed `#()` path intentionally small.
Line 0 runs `tmux-agent-status`, line 1 runs `tmux-git-status`, and both source a
per-pane cache written by one long-running `tmux-status-renderd` process. The
readers do not inspect processes, parse transcripts, run Python or git, or make
network requests.

## Render Tick

Each daemon tick performs these bounded stages:

1. Enumerate all tmux panes once and take one process-table snapshot.
2. Load Claude live-session files and identify Claude/Codex descendants for each
   pane. Choose the nearest descendant, using newest process start time for a
   tie.
3. Resolve selected Codex PIDs to exact open rollout files. Linux reads
   `/proc/<pid>/fd`; macOS runs one batched `lsof` command. Missing or multiple
   rollout paths are treated as unknown.
4. Adapt the provider source into a normalized agent record.
5. Compute the independent git line and atomically replace
   `~/.cache/tmux-status/render/pane-<pid>.env`.
6. Remove caches for pane PIDs that no longer exist.

`SIGUSR1` wakes the daemon for an immediate tick after infrequent structural
tmux events. The regular interval and singleton guard prevent overlapping work.

## Provider Adapters

Claude keeps its existing precedence: exact live-session transcript, then the
statusLine bridge for fresh sessions; live bridge effort/thinking overrides
transcript/settings fallbacks. Claude context comes from the bridge. Optional
Claude quota comes from the dedicated local/remote Claude quota service.

Codex reads backward from the tail of the exact open rollout, expanding the scan
only until it finds the latest valid `turn_context`, `task_started`, and
`token_count`. Those records
supply model/effort, context capacity/usage, and up to two rate-limit windows.
Malformed, truncated, partial, and additional fields cannot abort a tick.

Codex support is read-only and local: there are no Codex hooks, Codex config
mutations, OpenAI API calls, or requests to the Claude quota service.

## Cache Contract

Agent data uses shell-quoted `AGENT_*` keys: provider, raw/short model, effort,
thinking, context percentage, quota health, and two optional quota slots. Each
slot contains a duration, reset countdown, and percentage. `GIT_LINE` remains
independent, and `RENDER_TS` lets readers add a freshness marker without
recomputing data.

Non-agent panes contain only `GIT_LINE` and `RENDER_TS`, so line 0 remains blank.
`tmux-claude-status` sources `tmux-agent-status` as a compatibility alias for old
installations and already-loaded tmux configurations.
