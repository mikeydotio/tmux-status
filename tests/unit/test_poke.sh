#!/usr/bin/env bash
# Unit test: tmux-status-poke wakes the render daemon safely, and only it.
#
# Verifies the identity-verified signalling contract (TS-52):
#   1. A valid, live PID in renderd.lock whose command line actually names
#      tmux-status-renderd receives SIGUSR1 (tested against a real process
#      that traps the signal — `kill` is a bash builtin and cannot be
#      PATH-shimmed, so we observe the real delivery).
#   2. A missing lock file does nothing (no broadcast) and exits 0.
#   3. A non-numeric lock value is rejected (no signal to a bogus target) and
#      exits 0.
#   4. An empty lock value is rejected the same way.
#   5. A live PID recorded in the lock, but whose command line does NOT name
#      tmux-status-renderd, is not signalled (pid-reuse guard).
#
# A recording shim rejects any attempt to use the removed pkill-by-name
# fallback: no verified live renderd is exactly the state of a booting daemon.
# See the startup-safety integration test for the end-to-end regression proof.
#
# Mocks DATA (lock-file contents and processes), never the script itself.
# Portable to bash 3.2 (macOS default).

set -u
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
POKE="$REPO_ROOT/scripts/tmux-status-poke"

fail=0
pass() { printf '  PASS  %s\n' "$1"; }
die()  { printf '  FAIL  %s\n' "$1"; fail=$((fail + 1)); }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/poke-test.XXXXXX")"
TARGET_PID=""
DECOY_PID=""
cleanup() {
    [ -n "$TARGET_PID" ] && kill "$TARGET_PID" 2>/dev/null
    [ -n "$DECOY_PID" ] && kill "$DECOY_PID" 2>/dev/null
    rm -rf "$WORK"
}
trap cleanup EXIT

export HOME="$WORK"
LOCKDIR="$WORK/.cache/tmux-status/render"
LOCK="$LOCKDIR/renderd.lock"
SHIMBIN="$WORK/shim"
PKILL_CALLED="$WORK/pkill-called"
mkdir -p "$LOCKDIR" "$SHIMBIN"

# The RED implementation still broadcasts with pkill when the lock is absent
# or stale. Intercept that external command so this test can prove the call is
# forbidden without ever signalling the user's real daemon.
cat > "$SHIMBIN/pkill" <<SHIM
#!/bin/sh
touch "$PKILL_CALLED"
exit 0
SHIM
chmod +x "$SHIMBIN/pkill"

# ── Test 1: verified live renderd PID receives SIGUSR1 ─────────────────
echo "TEST 1: live renderd PID in lock -> receives SIGUSR1..."
SENTINEL="$WORK/got-usr1"
READY="$WORK/target-ready"
cat > "$WORK/tmux-status-renderd" <<TARGET
#!/usr/bin/env bash
trap 'touch "$SENTINEL"' USR1
touch "$READY"
while true; do sleep 0.2; done
TARGET
chmod +x "$WORK/tmux-status-renderd"
bash "$WORK/tmux-status-renderd" & TARGET_PID=$!
disown 2>/dev/null || true  # suppress async job-control "Terminated" notice on kill

# Wait until the trap is armed (READY appears).
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
    [ -f "$READY" ] && break
    sleep 0.1
done
printf '%s\n' "$TARGET_PID" > "$LOCK"

rm -f "$PKILL_CALLED"
out="$(PATH="$SHIMBIN:$PATH" bash "$POKE")"; rc=$?
# Wait up to ~3s for the trap to fire.
got=""
for _ in $(seq 1 30); do
    [ -f "$SENTINEL" ] && { got=1; break; }
    sleep 0.1
done
[ -n "$got" ] && pass "live renderd PID received SIGUSR1" || die "SIGUSR1 not delivered to live renderd PID"
[ "$rc" -eq 0 ] && pass "exit 0 on success path" || die "rc=$rc on success path"
[ -z "$out" ] && pass "no stray output on success" || die "unexpected output: $out"
[ ! -f "$PKILL_CALLED" ] && pass "no process-name broadcast on success" || die "pkill fallback was called"

kill "$TARGET_PID" 2>/dev/null; TARGET_PID=""

# ── Test 2: missing lock file -> no signal, no broadcast ───────────────
echo "TEST 2: missing lock -> no-op..."
rm -f "$LOCK"
rm -f "$PKILL_CALLED"
out="$(PATH="$SHIMBIN:$PATH" bash "$POKE")"; rc=$?
[ "$rc" -eq 0 ] && pass "exit 0 on missing-lock path" || die "rc=$rc on missing-lock path"
[ -z "$out" ] && pass "no stray output on missing-lock path" || die "unexpected output: $out"
[ ! -f "$PKILL_CALLED" ] && pass "missing lock does not broadcast" || die "missing lock called pkill"

# ── Test 3: non-numeric lock -> rejected, no signal ────────────────────
echo "TEST 3: garbage lock -> rejected, no-op..."
printf 'not-a-pid\n' > "$LOCK"
rm -f "$PKILL_CALLED"
out="$(PATH="$SHIMBIN:$PATH" bash "$POKE")"; rc=$?
[ "$rc" -eq 0 ] && pass "exit 0 on garbage-lock path" || die "rc=$rc on garbage-lock path"
[ -z "$out" ] && pass "no stray output on garbage-lock path" || die "unexpected output: $out"
[ ! -f "$PKILL_CALLED" ] && pass "garbage lock does not broadcast" || die "garbage lock called pkill"

# ── Test 4: empty lock -> rejected, no signal ──────────────────────────
echo "TEST 4: empty lock -> rejected, no-op..."
: > "$LOCK"
rm -f "$PKILL_CALLED"
out="$(PATH="$SHIMBIN:$PATH" bash "$POKE")"; rc=$?
[ "$rc" -eq 0 ] && pass "exit 0 on empty-lock path" || die "rc=$rc on empty-lock path"
[ -z "$out" ] && pass "no stray output on empty-lock path" || die "unexpected output: $out"
[ ! -f "$PKILL_CALLED" ] && pass "empty lock does not broadcast" || die "empty lock called pkill"

# ── Test 5: live non-renderd PID -> not signalled ──────────────────────
echo "TEST 5: live non-renderd PID in lock -> NOT signalled..."
DECOY_SENTINEL="$WORK/decoy-got-usr1"
DECOY_READY="$WORK/decoy-ready"
cat > "$WORK/some-unrelated-process.sh" <<DECOY
#!/usr/bin/env bash
trap 'touch "$DECOY_SENTINEL"' USR1
touch "$DECOY_READY"
while true; do sleep 0.2; done
DECOY
chmod +x "$WORK/some-unrelated-process.sh"
bash "$WORK/some-unrelated-process.sh" & DECOY_PID=$!
disown 2>/dev/null || true
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
    [ -f "$DECOY_READY" ] && break
    sleep 0.1
done
printf '%s\n' "$DECOY_PID" > "$LOCK"

rm -f "$PKILL_CALLED"
out="$(PATH="$SHIMBIN:$PATH" bash "$POKE")"; rc=$?
sleep 0.3
[ ! -f "$DECOY_SENTINEL" ] && pass "non-renderd PID was NOT signalled" || die "SIGUSR1 wrongly delivered to a non-renderd process"
[ "$rc" -eq 0 ] && pass "exit 0 on non-renderd-PID path" || die "rc=$rc on non-renderd-PID path"
[ -z "$out" ] && pass "no stray output on non-renderd-PID path" || die "unexpected output: $out"
[ ! -f "$PKILL_CALLED" ] && pass "unrelated PID does not broadcast" || die "unrelated PID called pkill"

kill "$DECOY_PID" 2>/dev/null; DECOY_PID=""

echo ""
if [ "$fail" -eq 0 ]; then
    echo "All poke checks passed."
    exit 0
else
    echo "$fail poke check(s) FAILED."
    exit 1
fi
