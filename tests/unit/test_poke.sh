#!/usr/bin/env bash
# Unit test: tmux-status-poke wakes the render daemon (or falls back) safely.
#
# Verifies the cold-start fix's signalling contract:
#   1. A valid, live PID in renderd.lock receives SIGUSR1 (tested against a real
#      process that traps the signal — `kill` is a bash builtin and cannot be
#      PATH-shimmed, so we observe the real delivery).
#   2. A missing lock file falls back to `pkill -USR1 -f tmux-status-renderd`.
#   3. A non-numeric lock value is rejected (no signal to a bogus target) and
#      falls back to pkill.
#   4. Every path exits 0 so a poke failure can never break its caller.
#
# Mocks DATA (lock-file contents) and the external pkill, never the script.
# Portable to bash 3.2 (macOS default).

set -u
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
POKE="$REPO_ROOT/scripts/tmux-status-poke"

fail=0
pass() { printf '  PASS  %s\n' "$1"; }
die()  { printf '  FAIL  %s\n' "$1"; fail=$((fail + 1)); }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/poke-test.XXXXXX")"
TARGET_PID=""
cleanup() {
    [ -n "$TARGET_PID" ] && kill "$TARGET_PID" 2>/dev/null
    rm -rf "$WORK"
}
trap cleanup EXIT

export HOME="$WORK"
LOCKDIR="$WORK/.cache/tmux-status/render"
LOCK="$LOCKDIR/renderd.lock"
mkdir -p "$LOCKDIR"

# A pkill shim so the fallback path is observable without signalling real
# processes. pkill has no bash builtin, so a PATH shim reliably intercepts it.
SHIMBIN="$WORK/shim"; mkdir -p "$SHIMBIN"
cat > "$SHIMBIN/pkill" <<SHIM
#!/bin/sh
touch "$WORK/PKILL-CALLED"
exit 0
SHIM
chmod +x "$SHIMBIN/pkill"

# ── Test 1: valid live PID is signalled with SIGUSR1 ───────────
echo "TEST 1: live PID in lock -> receives SIGUSR1..."
SENTINEL="$WORK/got-usr1"
READY="$WORK/target-ready"
cat > "$WORK/target.sh" <<TARGET
#!/usr/bin/env bash
trap 'touch "$SENTINEL"' USR1
touch "$READY"
while true; do sleep 0.2; done
TARGET
chmod +x "$WORK/target.sh"
bash "$WORK/target.sh" & TARGET_PID=$!
disown 2>/dev/null || true  # suppress async job-control "Terminated" notice on kill

# Wait until the trap is armed (READY appears).
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
    [ -f "$READY" ] && break
    sleep 0.1
done
printf '%s\n' "$TARGET_PID" > "$LOCK"

rm -f "$WORK/PKILL-CALLED"
out="$(PATH="$SHIMBIN:$PATH" bash "$POKE")"; rc=$?
# Wait up to ~3s for the trap to fire.
got=""
for _ in $(seq 1 30); do
    [ -f "$SENTINEL" ] && { got=1; break; }
    sleep 0.1
done
[ -n "$got" ] && pass "live PID received SIGUSR1" || die "SIGUSR1 not delivered to live PID"
[ "$rc" -eq 0 ] && pass "exit 0 on success path" || die "rc=$rc on success path"
[ -z "$out" ] && pass "no stray output on success" || die "unexpected output: $out"
[ ! -f "$WORK/PKILL-CALLED" ] && pass "did NOT fall back to pkill when PID signalled" || die "pkill fallback fired despite live PID"

kill "$TARGET_PID" 2>/dev/null; TARGET_PID=""

# ── Test 2: missing lock file -> pkill fallback ────────────────
echo "TEST 2: missing lock -> pkill fallback..."
rm -f "$LOCK" "$WORK/PKILL-CALLED"
out="$(PATH="$SHIMBIN:$PATH" bash "$POKE")"; rc=$?
[ -f "$WORK/PKILL-CALLED" ] && pass "missing lock falls back to pkill" || die "no pkill fallback on missing lock"
[ "$rc" -eq 0 ] && pass "exit 0 on missing-lock path" || die "rc=$rc on missing-lock path"

# ── Test 3: non-numeric lock -> rejected, pkill fallback ───────
echo "TEST 3: garbage lock -> rejected, pkill fallback..."
printf 'not-a-pid\n' > "$LOCK"; rm -f "$WORK/PKILL-CALLED"
out="$(PATH="$SHIMBIN:$PATH" bash "$POKE")"; rc=$?
[ -f "$WORK/PKILL-CALLED" ] && pass "non-numeric lock falls back to pkill" || die "no pkill fallback on garbage lock"
[ "$rc" -eq 0 ] && pass "exit 0 on garbage-lock path" || die "rc=$rc on garbage-lock path"

# ── Test 4: empty lock -> rejected, pkill fallback ─────────────
echo "TEST 4: empty lock -> rejected, pkill fallback..."
: > "$LOCK"; rm -f "$WORK/PKILL-CALLED"
out="$(PATH="$SHIMBIN:$PATH" bash "$POKE")"; rc=$?
[ -f "$WORK/PKILL-CALLED" ] && pass "empty lock falls back to pkill" || die "no pkill fallback on empty lock"
[ "$rc" -eq 0 ] && pass "exit 0 on empty-lock path" || die "rc=$rc on empty-lock path"

echo ""
if [ "$fail" -eq 0 ]; then
    echo "All poke checks passed."
    exit 0
else
    echo "$fail poke check(s) FAILED."
    exit 1
fi
