# Remediation Plan

## Root Cause (Summary)
The long-lived tmux server runs under a 256 soft fd limit (macOS launchd
default) while abandoned client connections pin its fd budget, so the
per-redraw `socketpair()` demand of tmux-status's `#()` jobs intermittently
exceeds 256 → `<'…' didn't start>`.

## Immediate Unblock (DONE)
Detached 43 clients idle > 6h. Server fds 120 → 34; high-water fd 226 → 110;
clients 52 → 9. Reversible (no session/process killed). Failures stop with
~220 fds of headroom restored.

## Durable Fixes (project hardening)

### Anti-Pattern Check
| Check | Pass/Fail | Notes |
|-------|-----------|-------|
| Not symptom masking | PASS | No try/catch around the readers; fixes the fd budget itself |
| Not a band-aid | PASS | Raises the resource ceiling + removes the fd hog at its origin |
| Not whack-a-mole | PASS | Helps every `#()` line on every pane, not one symptom |
| Removes flawed assumption | PASS | Drops the implicit "256 fds is enough for our `#()` workload" |
| Strengthens invariants | PASS | Documents "`#()` jobs cost server fds" as a maintained constraint |
| Simplifies / proportionate | PASS | Small launcher tweak + one helper + an install advisory + docs |

### Implementation Steps
1. **`scripts/tmux-status-session`** — raise `ulimit -n` (best-effort, capped to
   the hard limit) right before creating a fresh server, so launcher-created
   servers get ample fd headroom and inherit it for all `#()` jobs.
2. **`scripts/tmux-status-prune-clients`** (new) — detach clients idle beyond a
   threshold (default 6h) to reclaim server fds on demand; dry-run + test hooks;
   never kills sessions/processes; exits 0 with no server.
3. **`install.sh`** — symlink the new helper; add a best-effort advisory that
   reads the running server's real soft `RLIMIT_NOFILE` (via `tmux run-shell
   'ulimit -Sn'`, which dodges `.zshrc`) and warns with the fix when it's low.
4. **`uninstall.sh`** — clean up the new helper (and the previously-omitted
   `tmux-status-poke`) symlinks.
5. **README** — "Troubleshooting: status lines show `didn't start`" section.
6. **CLAUDE.md** — record the fd-budget constraint as an architectural invariant.
7. **Tests** — `tests/unit/test_prune_clients.sh` (threshold logic, injected
   clients/clock, no real tmux); syntax gate auto-covers the new script.

### Regression Prevention
- [ ] Test: prune helper detaches only clients past the idle threshold (boundary cases).
- [ ] Test: prune helper is a no-op / exits 0 when no clients / no server.
- [ ] Invariant (CLAUDE.md): every `#()` status job consumes one tmux-server fd;
      the server must run with a generous `ulimit -n`.

## Impact Assessment
### Files Modified
`scripts/tmux-status-session`, `scripts/tmux-status-prune-clients` (new),
`install.sh`, `uninstall.sh`, `README.md`, `CLAUDE.md`,
`tests/unit/test_prune_clients.sh` (new).

### Blast Radius
Launcher change only affects fresh-server creation. Prune helper is opt-in.
Install advisory is warn-only (never blocks). No change to the render path,
the per-pane cache contract, or the readers.

### Risk Level: LOW

## Alternative Fixes Considered
| Alternative | Why Not Chosen |
|-------------|----------------|
| Wrap readers in retry/try-catch | Symptom masking — the readers never ran |
| Auto-prune clients from the daemon | Too aggressive; detaching a user's client without consent is surprising |
| Collapse 3 `#()` lines into 1 | tmux `status-format` is per-line; can't fill 3 lines from one job; shaving 1 job doesn't fix a 256 ceiling pinned by clients |
| Raise the running server's limit externally | Impossible — `setrlimit` is self-only; `prlimit` is Linux-only |

## Lessons Learned
- `<'…' didn't start>` is a tmux *server* resource failure (socketpair/fork),
  not a script bug — diagnose the spawning process, not the spawned one.
- A pane shell's `ulimit -n` can be `.zshrc`-inflated; read the *server's* limit
  via `tmux run-shell` to avoid the red herring.
- Long-lived servers + mosh reconnect churn silently accrue fd-pinning clients;
  a fork-free render path still pays one server fd per `#()` job per redraw.
