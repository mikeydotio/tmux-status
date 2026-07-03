#!/usr/bin/env bash
# Contract gate: the overlay must invoke the thin readers with the cache key.
#
# The render daemon writes a per-pane cache keyed by PID (pane-<pid>.env) and the
# readers (tmux-claude-status / tmux-git-status) look it up by their first arg.
# So overlay/status.conf MUST pass "#{pane_pid}" to every reader. Commit 65b2f1d
# changed the git line to the pid contract but a running tmux server that was
# never re-sourced kept passing "#{pane_current_path}" — the new reader turned
# that path into a bogus cache filename, found nothing, and the git line went
# blank. This gate locks the writer/reader/config key so that drift fails
# `make test` instead of silently blanking a status line in production.
#
# Scoped to the reader-invocation lines only: "#{pane_current_path}" legitimately
# appears elsewhere in the overlay (e.g. automatic-rename-format).
# Portable to bash 3.2 (macOS default).
set -u

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CONF="$REPO_ROOT/overlay/status.conf"

fail=0
pass() { printf '  PASS  %s\n' "$1"; }
die()  { printf '  FAIL  %s\n' "$1"; fail=$((fail + 1)); }

[ -f "$CONF" ] || { echo "FAIL: $CONF not found" >&2; exit 1; }

# Reader-invocation lines = non-comment lines that call a reader script.
readers=0
while IFS= read -r line; do
    # Skip tmux comment lines (first non-blank char is '#').
    case "$(printf '%s' "$line" | sed 's/^[[:space:]]*//')" in
        '#'*) continue ;;
    esac
    case "$line" in
        *tmux-claude-status*|*tmux-git-status*) ;;
        *) continue ;;
    esac
    readers=$((readers + 1))

    case "$line" in
        *'#{pane_pid}'*) pass "reader passes #{pane_pid}: $(printf '%s' "$line" | sed 's/^[[:space:]]*//' | cut -c1-60)" ;;
        *) die "reader NOT keyed by #{pane_pid}: $line" ;;
    esac
    case "$line" in
        *pane_current_path*) die "reader keyed by pane_current_path (the 65b2f1d regression): $line" ;;
    esac
done < "$CONF"

# Guard against a vacuous gate: we expect the 3 reader lines (model, quota, git).
if [ "$readers" -lt 3 ]; then
    die "expected >=3 reader invocations in overlay, found $readers — gate may be matching nothing"
fi

# ── Pane-safety gate (view-mode hijack regression) ─────────────
# tmux renders ANY run-shell stdout — even backgrounded with -b — into the
# ACTIVE pane's view-mode, blanking its visible contents until dismissed. A
# background hook that prints even one line therefore hijacks the focused pane
# on every fire. This bit the client-attached prune hook: it emitted a one-line
# summary ("detached N idle client(s)..."), so every mosh/Moshtail reconnect
# cleared the user's pane. Every `run-shell -b` hook MUST redirect stdout+stderr
# so it stays silent to tmux. Portable to bash 3.2.
bghooks=0
while IFS= read -r line; do
    case "$(printf '%s' "$line" | sed 's/^[[:space:]]*//')" in
        '#'*) continue ;;
    esac
    case "$line" in
        *'run-shell -b'*) ;;
        *) continue ;;
    esac
    bghooks=$((bghooks + 1))
    case "$line" in
        *'>/dev/null'*|*'> /dev/null'*)
            pass "background -b hook redirects output: $(printf '%s' "$line" | sed 's/^[[:space:]]*//' | cut -c1-52)" ;;
        *)
            die "background 'run-shell -b' hook does NOT redirect stdout (tmux renders it into the active pane's view-mode, blanking the pane): $line" ;;
    esac
done < "$CONF"

# Guard against a vacuous gate: at least the prune + poke hooks are -b hooks.
if [ "$bghooks" -lt 1 ]; then
    die "expected >=1 'run-shell -b' hook in overlay, found $bghooks — pane-safety gate may be matching nothing"
fi

echo ""
if [ "$fail" -eq 0 ]; then
    echo "status.conf reader contract OK ($readers reader invocations checked)."
    exit 0
else
    echo "$fail status.conf contract check(s) FAILED."
    exit 1
fi
