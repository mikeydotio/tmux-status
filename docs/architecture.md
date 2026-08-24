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
   `/proc/<pid>/fd`; macOS runs one batched `lsof` command. A single open
   rollout is accepted directly. Multiple rollouts are grouped into root graphs
   through their `session_meta` parent links. Selection compares the latest
   valid event in each root rollout only, so background child activity cannot
   steal a pane. The pane's choice is sticky and switches only when another
   root has strictly newer root-thread activity.
4. Adapt the provider source into a normalized agent record.
5. Compute the independent git line and atomically replace
   `~/.cache/tmux-status/render/pane-<pid>.env`.
6. Persist the proven pane PID, Codex PID, process start times, root thread, and
   rollout path in `pane-<pid>.codex.json`, then remove env/selection caches for
   pane PIDs that no longer exist.

`SIGUSR1` wakes the daemon for an immediate tick after infrequent structural
tmux events. The regular interval and singleton guard prevent overlapping work.

## Provider Adapters

Claude keeps its existing precedence: exact live-session transcript, then the
statusLine bridge for fresh sessions; live bridge effort/thinking overrides
transcript/settings fallbacks. Claude context comes from the bridge. Optional
Claude quota comes from the dedicated local/remote Claude quota service.

Codex reads backward from the tail of the exact open rollout, expanding the scan
until it finds the latest valid `turn_context`, `task_started`, and `token_count`
plus the latest general `codex` rate-limit snapshot. Named model-specific limit
streams do not replace the general account quota. The freshest general snapshot
across exact active rollouts is shared by Codex panes. Malformed, truncated,
partial, and additional fields cannot abort a tick.

When several root graphs remain exact-open in one long-lived Codex process, the
selection sidecar restores the last proven root after a render-daemon restart.
Equal or malformed activity evidence leaves the prior pane env untouched, so it
remains visible with the normal stale marker instead of being replaced by a
blank agent line. Without a prior proven selection, genuine ambiguity fails
closed. A pane/Codex process lifecycle change or a rollout that is no longer
exact-open invalidates the sticky selection.

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
