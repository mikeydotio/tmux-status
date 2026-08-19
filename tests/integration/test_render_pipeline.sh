#!/usr/bin/env bash
# Integration test: render-daemon cache -> thin reader pipeline.
#
# Verifies the operational contract that makes the status bar fork-storm-proof:
#   1. A daemon-written per-pane cache renders Claude/Codex model/quota/git lines.
#   2. A cache miss (cold start) renders nothing and exits 0 (no fallback).
#   3. With a stale cache AND git/ps/python3 shimmed to fail, the readers STILL
#      print last-known values and exit 0 — proving they do NO heavy work and
#      never fall back to the old fork-heavy path (the whole point of the fix).
#   4. The real `tmux-status-renderd --once` runs without error.
#
# Mocks DATA (a fixture cache) but never BEHAVIOR (the real reader scripts run).

set -u
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
AGENT_READER="$REPO_ROOT/scripts/tmux-agent-status"
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
# Expected git line. The leading "~" is a literal in the fixture (the daemon
# collapses $HOME to ~), not a path to expand — build it so shellcheck does not
# read it as an intended tilde expansion (SC2088).
TILDE='~'
EXPECT_GIT="${TILDE}/work : main (clean)"

write_cache() {  # $1 = RENDER_TS value
    cat > "$ENVF" <<EOF
AGENT_PROVIDER=claude
AGENT_MODEL=claude-opus-4-8
AGENT_SHORT_MODEL='Opus 4.8'
AGENT_EFFORT=high
AGENT_HAS_THINKING=1
AGENT_CONTEXT_PCT=37
AGENT_QUOTA_STATUS=ok
AGENT_QUOTA_WARN=0
AGENT_QUOTA_1_DURATION=5h
AGENT_QUOTA_1_RESET=40m
AGENT_QUOTA_1_PCT=6
AGENT_QUOTA_2_DURATION=7d
AGENT_QUOTA_2_RESET=10.0h
AGENT_QUOTA_2_PCT=64
GIT_LINE='~/work : main (clean)'
RENDER_TS=$1
EOF
}

write_codex_cache() {  # $1 = RENDER_TS value
    cat > "$ENVF" <<EOF
AGENT_PROVIDER=codex
AGENT_MODEL=gpt-5.6-sol
AGENT_SHORT_MODEL='GPT-5.6 Sol'
AGENT_EFFORT=xhigh
AGENT_HAS_THINKING=''
AGENT_CONTEXT_PCT=21
AGENT_QUOTA_STATUS=ok
AGENT_QUOTA_WARN=0
AGENT_QUOTA_1_DURATION=7d
AGENT_QUOTA_1_RESET=5.1d
AGENT_QUOTA_1_PCT=14
AGENT_QUOTA_2_DURATION=''
AGENT_QUOTA_2_RESET=''
AGENT_QUOTA_2_PCT=''
GIT_LINE='~/work : main (clean)'
RENDER_TS=$1
EOF
}

# ── Test 1: fresh cache renders the expected lines ─────────────
echo "TEST 1: daemon cache -> reader renders combined-claude/git..."
write_cache 9999999999  # far-future TS => fresh, no stale marker
agent_out="$(bash "$AGENT_READER" "$PANE")"
claude_out="$(bash "$CLAUDE_READER" "$PANE")"
git_out="$(bash "$GIT_READER" "$PANE")"

# One combined line: model + effort + ctx%, then the 5h/7d quota bars.
case "$claude_out" in *"Opus 4.8"*"high"*"37%"*) pass "model+effort+ctx in combined line" ;; *) die "combined line: $claude_out" ;; esac
case "$claude_out" in *"40m"*"6%"*"64%"*) pass "quota bars in combined line" ;; *) die "combined line: $claude_out" ;; esac
[ "$agent_out" = "$claude_out" ] && pass "legacy Claude reader aliases primary agent reader" || die "alias output drifted"
# Cost was removed: no dollar amount may appear anywhere on the line.
case "$claude_out" in *'$'*) die "cost/dollar must be gone from the combined line: $claude_out" ;; *) pass "no dollar amounts" ;; esac
case "$claude_out" in *"⋯"*) die "fresh cache must NOT show stale marker: $claude_out" ;; *) pass "no stale marker when fresh" ;; esac
[ "$git_out" = "$EXPECT_GIT" ] && pass "git line content" || die "git line: $git_out"

# Codex quota includes both the window duration and reset countdown and omits
# an absent second window without adding a provider badge.
write_codex_cache 9999999999
codex_out="$(bash "$AGENT_READER" "$PANE")"
case "$codex_out" in *"GPT-5.6 Sol"*"xhigh"*"21%"*) pass "Codex model+effort+ctx" ;; *) die "Codex line: $codex_out" ;; esac
case "$codex_out" in *"7d/5.1d:"*"14%"*) pass "Codex window/reset quota" ;; *) die "Codex quota: $codex_out" ;; esac
case "$codex_out" in *"codex"*|*"Codex"*) die "line 0 must not add a provider badge: $codex_out" ;; *) pass "no provider badge" ;; esac

# An identified agent with only a model omits effort/context/quota segments.
cat > "$ENVF" <<EOF
AGENT_PROVIDER=codex
AGENT_MODEL=gpt-5.4
AGENT_SHORT_MODEL=GPT-5.4
RENDER_TS=9999999999
EOF
partial_out="$(bash "$AGENT_READER" "$PANE")"
case "$partial_out" in *"GPT-5.4"*) pass "partial record keeps model" ;; *) die "partial record: $partial_out" ;; esac
case "$partial_out" in *"Ctx:"*|*"│"*) die "partial record rendered missing segments: $partial_out" ;; *) pass "partial metrics omitted" ;; esac

# ── Test 2: cache miss renders nothing, exits 0 ────────────────
echo "TEST 2: cache miss -> silent, exit 0..."
miss_out="$(bash "$AGENT_READER" 999999)"; miss_rc=$?
[ -z "$miss_out" ] && [ "$miss_rc" -eq 0 ] && pass "agent reader silent on miss" || die "miss out=[$miss_out] rc=$miss_rc"
gmiss_out="$(bash "$GIT_READER" 999999)"; gmiss_rc=$?
[ -z "$gmiss_out" ] && [ "$gmiss_rc" -eq 0 ] && pass "git reader silent on miss" || die "git miss out=[$gmiss_out] rc=$gmiss_rc"

# ── Test 3: stale cache + heavy tools shimmed to fail -> still renders, no heavy work ─
echo "TEST 3: daemon-down (stale) -> last-known + NO heavy fork..."
write_cache 1  # ancient TS => stale
SHIMBIN="$WORK/shim"; mkdir -p "$SHIMBIN"
for cmd in git ps lsof python3 python curl; do
    cat > "$SHIMBIN/$cmd" <<SHIM
#!/bin/sh
touch "$SHIMBIN/CALLED-$cmd"
exit 99
SHIM
    chmod +x "$SHIMBIN/$cmd"
done
rm -f "$SHIMBIN"/CALLED-*
stale_claude="$(PATH="$SHIMBIN:$PATH" bash "$AGENT_READER" "$PANE")"; stale_rc=$?
stale_git="$(PATH="$SHIMBIN:$PATH" bash "$GIT_READER" "$PANE")"
# Still renders last-known content and exits 0:
case "$stale_claude" in *"Opus 4.8"*"37%"*) pass "stale: last-known model still rendered" ;; *) die "stale claude: $stale_claude" ;; esac
[ "$stale_rc" -eq 0 ] && pass "stale: reader exit 0" || die "stale rc=$stale_rc"
[ "$stale_git" = "$EXPECT_GIT" ] && pass "stale: last-known git still rendered" || die "stale git: $stale_git"
# CRITICAL: no heavy tool was ever forked.
heavy_called=""
for cmd in git ps lsof python3 python curl; do [ -e "$SHIMBIN/CALLED-$cmd" ] && heavy_called="$heavy_called $cmd"; done
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
