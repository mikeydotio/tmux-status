#!/usr/bin/env bash
# Unit tests for tmux-status-prune-clients.
#
# Drives the script through its test seams (TMUX_STATUS_CLIENTS,
# TMUX_STATUS_PRUNE_NOW) and --dry-run so no real tmux server is needed and no
# client is ever actually detached. Validates the idle-threshold decision,
# boundary behaviour, malformed-row handling, and the no-clients no-op.
#
# Portable to bash 3.2 (macOS default).
set -eu

REPO_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
SCRIPT="$REPO_ROOT/scripts/tmux-status-prune-clients"

NOW=1000000          # fixed "now" for deterministic idle math
pass=0
fail=0

# run <expected_detached> <expected_kept> <idle_threshold> <clients...desc> -- <client lines>
check() {
    local desc="$1" want_detach="$2" want_keep="$3" threshold="$4" clients="$5"
    local out got_detach got_keep
    out=$(TMUX_STATUS_PRUNE_NOW="$NOW" TMUX_STATUS_CLIENTS="$clients" \
          bash "$SCRIPT" --dry-run "$threshold")
    got_detach=$(printf '%s\n' "$out" | sed -n 's/.*would detach \([0-9]*\) idle.*/\1/p')
    got_keep=$(printf '%s\n' "$out" | sed -n 's/.*keep \([0-9]*\)\.$/\1/p')
    if [ "$got_detach" = "$want_detach" ] && [ "$got_keep" = "$want_keep" ]; then
        echo "  PASS  $desc (detach=$got_detach keep=$got_keep)"
        pass=$((pass + 1))
    else
        echo "  FAIL  $desc — want detach=$want_detach keep=$want_keep, got detach=${got_detach:-?} keep=${got_keep:-?}" >&2
        echo "        output: $out" >&2
        fail=$((fail + 1))
    fi
}

TAB=$(printf '\t')

# Threshold 21600s (6h). NOW=1000000.
#   activity 1000000 -> idle 0       (keep)
#   activity  978400 -> idle 21600   (== threshold, NOT > threshold -> keep)
#   activity  978399 -> idle 21601   (> threshold -> detach)
#   activity  900000 -> idle 100000  (detach)
check "two stale, one fresh" 2 1 21600 \
    "900000${TAB}/dev/ttys1
978399${TAB}/dev/ttys2
1000000${TAB}/dev/ttys3"

check "boundary: idle == threshold is kept" 0 1 21600 \
    "978400${TAB}/dev/ttys1"

check "boundary: idle == threshold+1 is detached" 1 0 21600 \
    "978399${TAB}/dev/ttys1"

check "all fresh" 0 3 21600 \
    "1000000${TAB}/dev/ttysA
999990${TAB}/dev/ttysB
995000${TAB}/dev/ttysC"

check "all stale" 3 0 3600 \
    "900000${TAB}/dev/ttysA
800000${TAB}/dev/ttysB
700000${TAB}/dev/ttysC"

check "malformed rows are skipped" 1 1 21600 \
    "notanumber${TAB}/dev/bad
900000${TAB}/dev/ttys1
1000000${TAB}/dev/ttys2"

# No clients at all → no-op, exits 0.
check "no clients is a no-op" 0 0 21600 ""

# Exit code is always 0.
if TMUX_STATUS_PRUNE_NOW="$NOW" TMUX_STATUS_CLIENTS="" bash "$SCRIPT" >/dev/null 2>&1; then
    echo "  PASS  exits 0 with no clients"
    pass=$((pass + 1))
else
    echo "  FAIL  expected exit 0 with no clients" >&2
    fail=$((fail + 1))
fi

# Default threshold (no numeric arg) comes from TMUX_STATUS_PRUNE_IDLE env.
out=$(TMUX_STATUS_PRUNE_NOW="$NOW" TMUX_STATUS_PRUNE_IDLE=100 \
      TMUX_STATUS_CLIENTS="999000${TAB}/dev/ttys1" bash "$SCRIPT" --dry-run)
if printf '%s\n' "$out" | grep -q 'would detach 1 idle'; then
    echo "  PASS  TMUX_STATUS_PRUNE_IDLE sets the default threshold"
    pass=$((pass + 1))
else
    echo "  FAIL  TMUX_STATUS_PRUNE_IDLE default threshold not honoured" >&2
    echo "        output: $out" >&2
    fail=$((fail + 1))
fi

# ── --reap-transport: kill the mosh-server/sshd-session behind detached clients ──
# Resolution is driven off an injected process snapshot (TMUX_STATUS_PS): rows are
# "<pid> <ppid> <tty> <comm>". The transport is a tty session-leader's off-tty
# parent, reaped only when it's a known network transport (mosh-server /
# sshd-session / sshd) — a local terminal's emulator/`login` is spared.
check_contains() {   # <desc> <needle> <haystack>
    if printf '%s\n' "$3" | grep -qF -- "$2"; then
        echo "  PASS  $1"; pass=$((pass + 1))
    else
        echo "  FAIL  $1 — missing: $2" >&2
        echo "        output: $3" >&2
        fail=$((fail + 1))
    fi
}
check_absent() {     # <desc> <needle> <haystack>
    if printf '%s\n' "$3" | grep -qF -- "$2"; then
        echo "  FAIL  $1 — unexpected: $2" >&2
        echo "        output: $3" >&2
        fail=$((fail + 1))
    else
        echo "  PASS  $1"; pass=$((pass + 1))
    fi
}

# Three stale clients (mosh-backed, LOCAL ghostty-via-login, sshd-backed) + one
# fresh mosh-backed client. NOW=1000000, threshold 3600.
REAP_CLIENTS="900000${TAB}/dev/ttys38
900000${TAB}/dev/ttys5
900000${TAB}/dev/ttys7
1000000${TAB}/dev/ttys1"
REAP_PS="30163 30162 ttys38 /opt/homebrew/bin/zsh
30162 1 ?? /opt/homebrew/bin/mosh-server
30515 30163 ttys38 /opt/homebrew/bin/tmux
80395 80394 ttys5 /bin/zsh
80394 1439 ttys5 /usr/bin/login
1439 1 ?? /Applications/Ghostty.app/Contents/MacOS/ghostty
50001 50000 ttys7 /bin/zsh
50000 1 ?? /usr/sbin/sshd-session
40000 39999 ttys1 /bin/zsh
39999 1 ?? /opt/homebrew/bin/mosh-server"

out=$(TMUX_STATUS_PRUNE_NOW="$NOW" TMUX_STATUS_CLIENTS="$REAP_CLIENTS" \
      TMUX_STATUS_PS="$REAP_PS" bash "$SCRIPT" --dry-run --reap-transport 3600)
check_contains "reap: mosh-server 30162 flagged"        "would reap transport 30162" "$out"
check_contains "reap: sshd-session 50000 flagged"       "would reap transport 50000" "$out"
check_absent   "reap: local ghostty (1439) spared"      "1439" "$out"
check_absent   "reap: local login (80394) spared"       "80394" "$out"
check_absent   "reap: fresh client transport (39999) spared" "39999" "$out"
check_contains "reap: summary counts 2 transports"      "would reap 2 transport(s)" "$out"
check_contains "reap: 3 detached / 1 kept"              "would detach 3 idle client(s), keep 1" "$out"

# Without --reap-transport, no transport is touched and the summary omits reaping.
out=$(TMUX_STATUS_PRUNE_NOW="$NOW" TMUX_STATUS_CLIENTS="$REAP_CLIENTS" \
      TMUX_STATUS_PS="$REAP_PS" bash "$SCRIPT" --dry-run 3600)
check_absent   "no-reap flag: no transport reaped"      "reap transport" "$out"
check_absent   "no-reap flag: summary has no reap count" "transport(s)" "$out"

# Real path (no --dry-run): the reaped pid is sent to the kill-log seam instead of
# an actual SIGTERM. A synthetic tty name that tmux would never assign keeps the
# unguarded `tmux detach-client` from matching a real client on the test machine.
KILL_LOG=$(mktemp 2>/dev/null || echo "/tmp/tmux-status-prune-kill.$$")
: > "$KILL_LOG"
REAP_PS_REAL="70001 70000 ttyFAKE /opt/homebrew/bin/zsh
70000 1 ?? /opt/homebrew/bin/mosh-server"
out=$(TMUX_STATUS_PRUNE_NOW="$NOW" TMUX_STATUS_CLIENTS="900000${TAB}/dev/ttyFAKE" \
      TMUX_STATUS_PS="$REAP_PS_REAL" TMUX_STATUS_KILL_LOG="$KILL_LOG" \
      bash "$SCRIPT" --reap-transport 3600)
if grep -qx "70000" "$KILL_LOG"; then
    echo "  PASS  reap real: mosh-server 70000 sent to kill-log"; pass=$((pass + 1))
else
    echo "  FAIL  reap real: expected 70000 in kill-log, got: $(cat "$KILL_LOG")" >&2
    fail=$((fail + 1))
fi
check_contains "reap real: summary says reaped 1"       "reaped 1 transport(s)" "$out"
rm -f "$KILL_LOG"

echo
echo "prune-clients tests: $pass passed, $fail failed."
[ "$fail" -eq 0 ]
