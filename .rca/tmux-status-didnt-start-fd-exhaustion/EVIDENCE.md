# Evidence Report

All evidence gathered live from the affected machine (read-only).

## The `didn't start` string is a tmux internal, not a script error
tmux emits `<'CMD' didn't start>` from its `format`/`job` subsystem when
`job_run()` returns NULL for a `#()` substitution. `job_run()` returns NULL
when **`socketpair()` fails** (out of file descriptors, EMFILE) or **`fork()`
fails** (out of processes, EAGAIN/ENOMEM). The readers never ran — so this is
NOT a bug inside `tmux-claude-status` / `tmux-git-status`. The constraint is in
the **tmux server process** that tries to spawn them.

## Process / fork budget — NOT the constraint
- `kern.maxprocperuid` = 10666; current uid process count = **1129** (~11%).
- Daemon coalesces wake signals: `render.py` uses a `threading.Event`
  (`wake.set()` is idempotent; `_loop` does `wake.wait(); wake.clear()`), so a
  burst of SIGUSR1 pokes produces back-to-back ticks, not N ticks. ~6 forks/tick.
- No stray `git`, reader, or poke processes at rest (counts = 0).
- Conclusion: process-table / fork-bomb exhaustion is **ruled out**.

## Memory — NOT the constraint
- `memory_pressure`: 84% free. `vm.swapusage`: 0.25M used of 1024M. No pressure.
- fork() ENOMEM ruled out.

## File descriptors — THE constraint
- macOS launchd default: `launchctl limit maxfiles` = **256** soft / unlimited hard.
- tmux server (pid 60185, alive 15 days) **actual** soft `RLIMIT_NOFILE` = **256**
  (read via `tmux run-shell 'ulimit -Sn'`, which forks a plain `/bin/sh` child of
  the server with no `.zshrc`). The interactive shell reports 1048576 — that is
  `.zshrc` raising the limit *after* inheriting 256, and is a RED HERRING; the
  server itself was started before/without that raise.
- tmux server currently holds **118 open fds**, **highest fd number = 226**
  (i.e. has operated within ~30 fds of the 256 ceiling).
- fd type breakdown: **64 unix sockets** (of which **52 are client connections**),
  58 CHR (ptys/devices), 5 REG, 2 PIPE, 1 DIR.

## The fd hog — accumulated abandoned clients
- `tmux list-clients`: **51 clients**, ALL attached to the single `Psamathe`
  session, with `activity` timestamps spanning **June 8 → June 24** (today).
  Most are days/weeks stale — abandoned mosh reconnects that never detached.
- **71 `mosh-server`** processes and **52 `tmux attach`** clients accumulated
  (mosh-over-Tailscale churn). Each live client = 1 permanent server fd.
- Net: ~51 of the server's 256 fds are permanently pinned by zombie clients,
  plus ~58 ptys/devices, leaving little headroom for the transient socketpairs
  that `#()` jobs require.

## Per-redraw fd demand from tmux-status (the trigger)
- `overlay/status.conf` lines 19/22/26: **three** `#()` reader jobs per pane,
  re-run every `status-interval` (=5s). Each job needs one server-side socketpair.
- `render.py` runs `tmux list-panes -a` every tick → a transient client
  connection to the server each tick (more fd churn), and poke storms make ticks
  run back-to-back.
- `client-session-changed` set-hook (status.conf:63) fires on every mosh
  reconnect/session switch, each time spawning `tmux-status-poke` and triggering
  redraws — concentrating `#()` job creation into bursts.

## Key Facts (ranked)
1. tmux server soft fd limit = **256** (measured, server-real).
2. **51 abandoned clients** pin ~51 fds; server high-water fd = 226/256.
3. Memory and process limits are not near their ceilings.
4. Symptom (`didn't start`) is precisely the `socketpair()`-EMFILE signature.
5. Only `#()` lines fail; the native line 3 (no job) always renders.
