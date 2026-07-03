#!/usr/bin/env bash
# Integration test: overlay/status.conf background hooks never hijack a pane.
#
# The bug this guards (fixed in v2.4.1): tmux renders ANY `run-shell` stdout —
# even backgrounded with `-b` — into the ACTIVE pane's view-mode, blanking the
# pane's visible contents and displaying the text until dismissed. The
# `client-attached` prune hook ran a script that always prints a one-line
# summary, so every client attach (each mosh/Moshtail reconnect) cleared the
# user's focused pane. The static gate in tests/unit/test_status_conf_contract.sh
# asserts every `run-shell -b` hook line carries a `>/dev/null 2>&1` redirect;
# THIS test proves the redirect actually works against a live tmux server — the
# failure mode only manifests with a real server rendering a real hook command,
# which `make test` otherwise never exercised.
#
# How it stays honest (non-vacuous):
#   * A fake $HOME with LOUD stubs at ~/.local/bin/tmux-status-{poke,prune-clients}
#     stands in for the real scripts, so the hook paths resolve to something that
#     DOES emit output. Pass/fail then hinges solely on the redirect in the real
#     config line — not on install state, and with zero risk of a real reap.
#   * A POSITIVE CONTROL fires the stub WITHOUT a redirect and asserts the pane
#     DOES enter view-mode. If that ever fails (stub not found, tmux behavior
#     changed, detector broken) the whole test is vacuous, so it hard-fails.
#
# Mocks the referenced binaries (DATA) but never the tmux hook behavior we test.

set -u
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CONF="$REPO_ROOT/overlay/status.conf"

fail=0
pass() { printf '  PASS  %s\n' "$1"; }
die()  { printf '  FAIL  %s\n' "$1"; fail=$((fail + 1)); }

[ -f "$CONF" ] || { echo "FAIL: $CONF not found" >&2; exit 1; }

if ! command -v tmux >/dev/null 2>&1; then
    echo "  SKIP  tmux not installed — cannot run live pane-safety checks"
    exit 0
fi

# ── Fake HOME with loud stubs standing in for the real hook scripts ───────────
FAKE_HOME="$(mktemp -d "${TMPDIR:-/tmp}/hook-pane-safety.XXXXXX")"
SOCK="tmux-status-panesafe-$$"
cleanup() {
    tmux -L "$SOCK" kill-server >/dev/null 2>&1
    rm -rf "$FAKE_HOME"
}
trap cleanup EXIT
export HOME="$FAKE_HOME"   # set BEFORE the server starts so run-shell's ~ expands here

mkdir -p "$FAKE_HOME/.local/bin"
for name in tmux-status-poke tmux-status-prune-clients; do
    cat > "$FAKE_HOME/.local/bin/$name" <<STUB
#!/bin/sh
# Loud stub: emits on BOTH streams so the real hook's \`>/dev/null 2>&1\` is fully
# exercised. If this output reaches tmux, it hijacks the active pane.
echo "STUB $name: detached 0 idle client(s), kept 4, reaped 0 transport(s)."
echo "STUB $name: stderr line" >&2
exit 0
STUB
    chmod +x "$FAKE_HOME/.local/bin/$name"
done

# ── Scratch server: no user config (-f /dev/null), one stable long-lived pane ──
tmux -L "$SOCK" -f /dev/null new-session -d -s t -x 80 -y 24 'sleep 100000' \
    || { die "could not start scratch tmux server"; echo; echo "$fail check(s) FAILED."; exit 1; }
PANE_ID="$(tmux -L "$SOCK" display-message -p -t t '#{pane_id}')"

# Fire a command via `run-shell -b` and report the resulting pane_in_mode.
# Resets any prior mode first, then polls: returns "1" as soon as the pane is
# hijacked (fast path for the positive control), else "0" after a settle window
# ample for an echo-stub's async completion (slow path for the safe hooks).
fire_mode() {  # $1 = shell command to run in the hook context
    tmux -L "$SOCK" send-keys -t "$PANE_ID" -X cancel >/dev/null 2>&1
    tmux -L "$SOCK" run-shell -b "$1"
    local i=0 m=0
    while [ "$i" -lt 15 ]; do
        m="$(tmux -L "$SOCK" display-message -p -t "$PANE_ID" '#{pane_in_mode}' 2>/dev/null)"
        [ "$m" = "1" ] && break
        sleep 0.1
        i=$((i + 1))
    done
    printf '%s' "$m"
}

# ── Positive control: proves the harness can actually detect a hijack ─────────
# Same stub, but WITHOUT the redirect — its output must throw the pane into
# view-mode. If not, every assertion below would be meaningless, so fail hard.
echo "POSITIVE CONTROL: unredirected hook output must hijack the pane..."
pc="$(fire_mode '~/.local/bin/tmux-status-prune-clients')"
if [ "$pc" = "1" ]; then
    pass "unredirected stub output hijacks the active pane (detector is live)"
else
    die "positive control FAILED (in_mode=$pc): stub did not hijack — test would be vacuous, ABORTING"
    tmux -L "$SOCK" send-keys -t "$PANE_ID" -X cancel >/dev/null 2>&1
    echo; echo "$fail pane-safety check(s) FAILED."; exit 1
fi

# ── The real hooks: every `run-shell -b` line in status.conf must stay silent ──
echo "REAL HOOKS: each background run-shell -b hook must leave the pane clean..."
bghooks=0
while IFS= read -r line; do
    # Skip tmux comment lines (first non-blank char is '#').
    case "$(printf '%s' "$line" | sed 's/^[[:space:]]*//')" in
        '#'*) continue ;;
    esac
    case "$line" in
        *'run-shell -b'*) ;;
        *) continue ;;
    esac
    # Extract the inner command from: set-hook -g <name> 'run-shell -b "<cmd>"'
    cmd="$(printf '%s\n' "$line" | sed -n 's/.*run-shell -b "\([^"]*\)".*/\1/p')"
    [ -n "$cmd" ] || { die "could not parse hook command from: $line"; continue; }
    hookname="$(printf '%s\n' "$line" | sed -n 's/^[[:space:]]*set-hook -g \([^ ]*\).*/\1/p')"
    [ -n "$hookname" ] || hookname="(hook)"
    bghooks=$((bghooks + 1))

    m="$(fire_mode "$cmd")"
    if [ "$m" = "0" ]; then
        pass "$hookname: pane stays clean (in_mode=0)"
    else
        die "$hookname: HIJACKED the pane (in_mode=$m) — missing/broken redirect: $cmd"
    fi
done < "$CONF"

# Guard against a vacuous sweep: at least the prune + poke hooks exist.
if [ "$bghooks" -lt 1 ]; then
    die "no 'run-shell -b' hooks found in overlay — sweep matched nothing"
fi

echo ""
if [ "$fail" -eq 0 ]; then
    echo "All hook pane-safety checks passed ($bghooks background hook(s) verified live)."
    exit 0
else
    echo "$fail pane-safety check(s) FAILED."
    exit 1
fi
