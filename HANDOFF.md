# HANDOFF — mosh-orphan fork-storm: incident resolved, prevention pending

## What happened (2026-07-03)

System load average hit **~105 on a 10-core Mac** (sustained; even `ps | grep` timed out).
Root cause: **34 tmux clients** attached to a single 4-pane session, ~33 of them
**abandoned mosh/SSH reconnects** (33 orphaned `mosh-server`, ages to 3 days; 8 orphaned
`mikey@notty` sshd-sessions). tmux forks the status-bar `#()` readers per client per
`status-interval` (5s), so N orphan clients = an N× fork storm. This is the CPU-fork-storm
sibling of `.rca/tmux-status-didnt-start-fd-exhaustion/` — same root (client pile-up),
different symptom (the server fd budget was fine at 8192/168-used; CPU was the wall).

**Upstream source = Moshtail** (`../moshtail`, the iOS mosh client). Mosh cross-process
resume is protocol-impossible + Moshtail's resume state is in-memory only, so every cold
app relaunch (iOS suspend/kill) spawns a NEW `mosh-server` and can't reap the old. It also
leaks the libssh2 SSH bootstrap connection (no `SSHClient.deinit`, never `close()`d on the
mosh path) → the `@notty` orphans. Because iOS kills the app without notice, the client
can never be trusted to self-clean — **the Mac must self-heal.**

## Resolution (done)

- `tmux-status-prune-clients 3600` → detached 33 idle clients (kept active ttys038).
- Killed 32 orphaned `mosh-server` procs, protecting the active one (pid 30162, found via
  active client's login-shell ppid — every mosh-server is `ppid=1`, so parent can't
  distinguish orphan from live).
- **Result: load 105 → 2.84 (1-min) in ~10 min.** Clients/mosh-servers back to 1 each.
  No session/data lost (tmux server + panes + Claude are children of the tmux daemon, not
  any mosh-server). Full runbook saved in project memory `moshtail-mosh-orphan-forkstorm`.

## Prevention plan

### Layer 2 — Server auto-reap  ✅ SHIPPED (2A, 2B) — live on this machine
- **2A. Scheduled prune — DONE.** launchd agent `io.mikey.tmux-status-prune` (macOS,
  `StartInterval 1800`, `RunAtLoad false`) + systemd `tmux-status-prune.timer` (Linux,
  every ~30m). Runs `tmux-status-prune-clients --reap-transport 7200`. Deploy files in
  `server/deploy/`, wired into install.sh/uninstall.sh. Loaded and verified live.
- **2B. `--reap-transport` — DONE.** For each idle client detached, resolve pty→backing
  `mosh-server`/`sshd-session` (session-leader's off-tty parent via a `ps` snapshot) and
  kill it. Allowlisted (local terminal `login`/emulator spared); only idle-past-threshold
  clients, so the active session is always safe. Script prepends Homebrew/local PATH so
  `tmux` resolves under launchd/cron. 20 unit tests (incl. real ps-snapshot smoke) green.
- **2C. sshd keepalive drop-in — STILL TODO (needs sudo).**
  `/etc/ssh/sshd_config.d/200-keepalive.conf` → `ClientAliveInterval 300`,
  `ClientAliveCountMax 2`, then reload sshd. Current effective value is
  `ClientAliveInterval 0` = never drops dead ssh → the `@notty` leaks. Mikey must run sudo.

### Layer 3 — tmux-status hardening  ✅ SHIPPED (3A) — live
- **3A. Event-driven prune — DONE.** `set-hook -g client-attached` in
  `overlay/status.conf` runs `tmux-status-prune-clients --reap-transport 7200` (run-shell
  -b). Every new (e.g. Moshtail) attach self-prunes stale clients; bounds accumulation to
  the idle window. Verified live (`tmux show-hooks -g | grep client-attached`).
- **3B.** (optional) raise `status-interval` 5s→10-15s. Low priority now 2A/2B/3A cap client count.
- **3C.** (optional) warn (renderd / a `doctor` cmd) when attached-client count > ~6.

### Layer 1 — Moshtail client (source-rate fix; separate repo `../moshtail`) — TODO
Reduces orphan *creation* at the source; server-side (2A/2B/3A) already guarantees cleanup.
Ranked from the source review (see memory `moshtail-mosh-orphan-forkstorm` for file:line):
1. Close the SSH bootstrap connection — `defer { await ssh.close() }` on mosh paths +
   `SSHClient.deinit`. Smallest change, kills `@notty` at source.
2. Reap-on-connect host sweep before `mosh-server new` (uses the already-open SSH channel).
3. Kill-on-deliberate-disconnect (SSH-kill the known-port server).
4. `tmux new-session -A -s moshtail` in on-connect config; stop replaying `attach` on escalation.
5. `MOSH_SERVER_NETWORK_TMOUT` self-destruct — caveat: version-dependent/finicky, verify
   against the Mac's mosh 1.4.0 first.

## Remaining
- **2C** (sshd `ClientAliveInterval`, needs sudo) and **Layer 1** (Moshtail, separate repo).
- Consider scoping the Moshtail fixes as its own storyhook stories in that repo.
