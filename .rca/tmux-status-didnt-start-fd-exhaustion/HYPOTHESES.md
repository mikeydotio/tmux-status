# Hypothesis Report

## 5 Whys (verified chain)
1. **Symptom:** Status lines show `<'…tmux-claude-status "76272" model' didn't start>`.
2. **Why?** tmux's `job_run()` returned NULL for those `#()` jobs — the child
   was never spawned.
3. **Why?** `job_run()` returns NULL when `socketpair()` (or `fork()`) fails.
   Memory/process limits are fine → it is `socketpair()` failing with EMFILE.
4. **Why?** The tmux server hit its file-descriptor ceiling during a redraw that
   needed several new socketpairs at once.
5. **Why?** The server's soft `RLIMIT_NOFILE` is only **256** (macOS launchd
   default) and **51 abandoned clients permanently pin ~51 fds**, leaving too
   little transient headroom (high-water 226/256).
6. **Root cause:** The long-lived tmux server runs under a 256-fd soft limit it
   never raised, while accumulating long-lived client connections (mosh
   reconnect churn) that consume the fd budget — so the per-redraw socketpair
   demand of tmux-status's `#()` jobs intermittently exceeds 256.

## Fishbone
| Category | Cause |
|----------|-------|
| Environment | tmux server soft `RLIMIT_NOFILE` = 256 (launchd default) — **primary** |
| Data/State  | 51 abandoned mosh/tmux clients pinning ~51 fds — **primary hog** |
| Code (tmux-status) | 3 `#()` jobs/pane/5s + per-tick `tmux list-panes -a` + poke-burst redraws raise transient fd demand — **trigger/amplifier** |
| Code | Process/fork pressure — ruled out (1129/10666) |
| Environment | Memory pressure — ruled out (84% free) |

## Hypotheses (ranked)

### H1 — fd exhaustion in the tmux server — Confidence: HIGH ✅ VERIFIED
- **Statement:** The server intermittently exceeds its 256 soft fd limit because
  ~51 abandoned clients pin the budget, so `socketpair()` for new `#()` jobs
  fails → `didn't start`.
- **Evidence for:** server soft NOFILE=256 (measured); 51 clients; high-water
  226/256; only `#()` lines fail; memory & procs fine; exact EMFILE signature.
- **Evidence against:** none found.
- **Falsification test:** With the limit at 256, freeing client fds should
  restore headroom and stop the failures; conversely a server started with a
  high `ulimit -n` should never show `didn't start`. (See VERIFICATION.)
- **Prevents recurrence?** Yes — raise the limit + prune fd hogs + cut per-redraw
  job demand.

### H2 — fork/process exhaustion (user's "fork-bomb") — Confidence: LOW ❌ REFUTED
- Process count 1129/10666; daemon coalesces pokes; no stray children. Ruled out.

### H3 — memory-pressure fork() ENOMEM — Confidence: LOW ❌ REFUTED
- 84% memory free, ~0 swap. Ruled out.

### H4 — bug inside the reader scripts — Confidence: LOW ❌ REFUTED
- `didn't start` means the readers never executed; the failure is upstream in
  tmux's job spawn, not in script logic.

## Recommended Investigation Priority
H1 only — verify the causal chain end-to-end (done).
