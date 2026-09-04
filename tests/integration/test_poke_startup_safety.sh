#!/usr/bin/env bash
# Integration regression for TS-52: a poke must not broadcast into renderd's
# SIGUSR1-fatal startup window.

set -u
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
POKE="$REPO_ROOT/scripts/tmux-status-poke"

fail=0
pass() { printf '  PASS  %s\n' "$1"; }
die()  { printf '  FAIL  %s\n' "$1"; fail=$((fail + 1)); }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/poke-startup-safety.XXXXXX")"
TARGET_PID=""
cleanup() {
    [ -n "$TARGET_PID" ] && kill "$TARGET_PID" 2>/dev/null
    rm -rf "$WORK"
}
trap cleanup EXIT

export HOME="$WORK/home"
LOCK_DIR="$HOME/.cache/tmux-status/render"
LOCK="$LOCK_DIR/renderd.lock"
SHIM_DIR="$WORK/shim"
mkdir -p "$LOCK_DIR" "$SHIM_DIR"

# Model a renderd process before its Python signal handler is armed. Its path
# deliberately matches the old pkill pattern, and SIGUSR1 retains the default
# fatal disposition throughout the controlled startup delay.
cat > "$WORK/tmux-status-renderd" <<'PYTHON'
#!/usr/bin/env python3
import os
import time

with open(os.environ["STARTUP_READY"], "w"):
    pass
time.sleep(30)
PYTHON
chmod +x "$WORK/tmux-status-renderd"

# Safe stand-in for `pkill -USR1 -f tmux-status-renderd`: it broadcasts only
# to the controlled target, so the regression can exercise the old behavior
# without risking the user's real daemon.
cat > "$SHIM_DIR/pkill" <<'SHIM'
#!/bin/sh
kill -USR1 "$BROADCAST_TARGET" 2>/dev/null || true
SHIM
chmod +x "$SHIM_DIR/pkill"

start_target() {
    STARTUP_READY="$WORK/ready-$1"
    export STARTUP_READY
    rm -f "$STARTUP_READY"
    "$WORK/tmux-status-renderd" & TARGET_PID=$!
    disown 2>/dev/null || true
    for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
        [ -f "$STARTUP_READY" ] && return
        sleep 0.1
    done
    die "$1 target never entered its startup window"
}

poke_storm() {
    BROADCAST_TARGET="$TARGET_PID"
    export BROADCAST_TARGET
    for _ in 1 2 3 4 5; do
        PATH="$SHIM_DIR:$PATH" bash "$POKE"
    done
    sleep 0.2
}

assert_survives() {
    if kill -0 "$TARGET_PID" 2>/dev/null; then
        pass "$1 survives the poke storm"
    else
        die "$1 was killed by a broadcast SIGUSR1"
    fi
    kill "$TARGET_PID" 2>/dev/null
    wait "$TARGET_PID" 2>/dev/null || true
    TARGET_PID=""
}

echo "TEST 1: --once warm-up with no lock survives pokes..."
rm -f "$LOCK"
start_target "warm-up"
poke_storm
assert_survives "--once warm-up"

echo "TEST 2: booting daemon with a stale lock survives pokes..."
printf '99999999\n' > "$LOCK"
start_target "daemon"
poke_storm
assert_survives "booting daemon"

echo ""
if [ "$fail" -eq 0 ]; then
    echo "All poke startup-safety checks passed."
    exit 0
fi

echo "$fail poke startup-safety check(s) FAILED."
exit 1
