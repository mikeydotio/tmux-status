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

echo
echo "prune-clients tests: $pass passed, $fail failed."
[ "$fail" -eq 0 ]
