#!/usr/bin/env bash
# Integration test: render-daemon cache -> thin reader pipeline.
#
# Verifies the operational contract that makes the status bar fork-storm-proof:
#   1. A daemon-written per-pane cache renders the expected model/quota/git lines.
#   2. A cache miss (cold start) renders nothing and exits 0 (no fallback).
#   3. With a stale cache AND git/ps/python3 shimmed to fail, the readers STILL
#      print last-known values and exit 0 — proving they do NO heavy work and
#      never fall back to the old fork-heavy path (the whole point of the fix).
#   4. The real `tmux-status-renderd --once` runs without error.
#
# Mocks DATA (a fixture cache) but never BEHAVIOR (the real reader scripts run).

set -u
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CLAUDE_READER="$REPO_ROOT/scripts/tmux-claude-status"
GIT_READER="$REPO_ROOT/scripts/tmux-git-status"

fail=0
pass() { printf '  PASS  %s\n' "$1"; }
die()  { printf '  FAIL  %s\n' "$1"; fail=$((fail + 1)); }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/render-pipeline.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
export HOME="$WORK"
RENDER_DIR="$WORK/.cache/tmux-status/render"
mkdir -p "$RENDER_DIR"

PANE=4242
ENVF="$RENDER_DIR/pane-${PANE}.env"

write_cache() {  # $1 = RENDER_TS value
    cat > "$ENVF" <<EOF
MODEL=claude-opus-4-8
SHORT_MODEL='Opus 4.8'
USED_PCT=37
EFFORT=high
HAS_THINKING=1
QUOTA_STATUS=ok
QUOTA_5H_PCT=6
QUOTA_5H_REMAIN=40m
QUOTA_7D_PCT=64
QUOTA_7D_REMAIN=10.0h
KEY_EXPIRY_WARN=0
SESSION_COST=0.06
DAILY_COST=1.23
GIT_LINE='~/work : main (clean)'
RENDER_TS=$1
EOF
}

# ── Test 1: fresh cache renders the expected lines ─────────────
echo "TEST 1: daemon cache -> reader renders model/quota/git..."
write_cache 9999999999  # far-future TS => fresh, no stale marker
model_out="$(bash "$CLAUDE_READER" "$PANE" model)"
quota_out="$(bash "$CLAUDE_READER" "$PANE" quota)"
git_out="$(bash "$GIT_READER" "$PANE")"

case "$model_out" in *"Opus 4.8"*"high"*"37%"*) pass "model line content" ;; *) die "model line: $model_out" ;; esac
case "$model_out" in *"⋯"*) die "fresh cache must NOT show stale marker: $model_out" ;; *) pass "no stale marker when fresh" ;; esac
case "$quota_out" in *"40m"*"6%"*"64%"*'$0.06'*'$1.23'*) pass "quota line content" ;; *) die "quota line: $quota_out" ;; esac
[ "$git_out" = "~/work : main (clean)" ] && pass "git line content" || die "git line: $git_out"

# ── Test 2: cache miss renders nothing, exits 0 ────────────────
echo "TEST 2: cache miss -> silent, exit 0..."
miss_out="$(bash "$CLAUDE_READER" 999999 model)"; miss_rc=$?
[ -z "$miss_out" ] && [ "$miss_rc" -eq 0 ] && pass "claude reader silent on miss" || die "miss out=[$miss_out] rc=$miss_rc"
gmiss_out="$(bash "$GIT_READER" 999999)"; gmiss_rc=$?
[ -z "$gmiss_out" ] && [ "$gmiss_rc" -eq 0 ] && pass "git reader silent on miss" || die "git miss out=[$gmiss_out] rc=$gmiss_rc"

# ── Test 3: stale cache + heavy tools shimmed to fail -> still renders, no heavy work ─
echo "TEST 3: daemon-down (stale) -> last-known + NO heavy fork..."
write_cache 1  # ancient TS => stale
SHIMBIN="$WORK/shim"; mkdir -p "$SHIMBIN"
for cmd in git ps python3 python; do
    cat > "$SHIMBIN/$cmd" <<SHIM
#!/bin/sh
touch "$SHIMBIN/CALLED-$cmd"
exit 99
SHIM
    chmod +x "$SHIMBIN/$cmd"
done
rm -f "$SHIMBIN"/CALLED-*
stale_model="$(PATH="$SHIMBIN:$PATH" bash "$CLAUDE_READER" "$PANE" model)"; stale_rc=$?
stale_git="$(PATH="$SHIMBIN:$PATH" bash "$GIT_READER" "$PANE")"
# Still renders last-known content and exits 0:
case "$stale_model" in *"Opus 4.8"*"37%"*) pass "stale: last-known model still rendered" ;; *) die "stale model: $stale_model" ;; esac
[ "$stale_rc" -eq 0 ] && pass "stale: reader exit 0" || die "stale rc=$stale_rc"
[ "$stale_git" = "~/work : main (clean)" ] && pass "stale: last-known git still rendered" || die "stale git: $stale_git"
# CRITICAL: no heavy tool was ever forked.
heavy_called=""
for cmd in git ps python3 python; do [ -e "$SHIMBIN/CALLED-$cmd" ] && heavy_called="$heavy_called $cmd"; done
[ -z "$heavy_called" ] && pass "NO heavy fork (git/ps/python) on the read path" || die "reader forked heavy tools:$heavy_called"

# ── Test 4: real `tmux-status-renderd --once` runs cleanly ─────
echo "TEST 4: tmux-status-renderd --once smoke..."
if python3 -c "import sys; sys.path.insert(0,'$REPO_ROOT/server'); import tmux_status_server.render" 2>/dev/null; then
    if python3 -c "import sys; sys.path.insert(0,'$REPO_ROOT/server'); from tmux_status_server import render; render.render_once(home='$WORK')" 2>/dev/null; then
        pass "render_once() ran without error"
    else
        die "render_once() raised"
    fi
else
    echo "  SKIP  render module not importable in this environment"
fi

echo ""
if [ "$fail" -eq 0 ]; then
    echo "All render-pipeline integration checks passed."
    exit 0
else
    echo "$fail render-pipeline check(s) FAILED."
    exit 1
fi
