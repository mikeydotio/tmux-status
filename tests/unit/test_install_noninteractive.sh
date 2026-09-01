#!/usr/bin/env bash
# Regression: install.sh and uninstall.sh must never block on input when stdin
# is not a TTY (piped installs, CI, `curl | bash`, a shell-tool invocation).
#
# A prompt was once added to install.sh's normal upgrade path without a TTY
# guard, which hung every non-interactive install partway through -- after the
# symlink step but before the server package was reinstalled, leaving a
# half-upgraded install. These checks kill that class:
#
#   1. Structural: every `read` is TTY-guarded (or behind a helper that is).
#   2. Behavioural: both scripts terminate with stdin closed.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAILED=0

pass() { printf '  \033[1;32mPASS\033[0m  %s\n' "$1"; }
fail() { printf '  \033[1;31mFAIL\033[0m  %s\n' "$1"; FAILED=1; }

# ---------------------------------------------------------------------------
# 1. Structural: no unguarded `read` in either script
# ---------------------------------------------------------------------------
echo "TEST 1: every interactive read is TTY-guarded..."

check_reads_guarded() {
    local script="$1" name="$2" unguarded=0

    while IFS=: read -r lineno _; do
        [ -n "$lineno" ] || continue
        # A read is guarded when a TTY test appears in the preceding 12 lines:
        # either a direct `[ -t 0 ]` or an is_interactive-style helper call.
        local start=$(( lineno > 12 ? lineno - 12 : 1 ))
        if sed -n "${start},${lineno}p" "$script" \
             | grep -qE '\[ *-t *0 *\]|is_interactive'; then
            continue
        fi
        fail "$name:$lineno — \`read\` with no TTY guard within 12 lines"
        unguarded=1
    done < <(grep -nE '^[[:space:]]*read[[:space:]]+-' "$script" || true)

    [ "$unguarded" -eq 0 ] && pass "$name: all reads TTY-guarded"
}

check_reads_guarded "$REPO_ROOT/install.sh" "install.sh"
check_reads_guarded "$REPO_ROOT/uninstall.sh" "uninstall.sh"

# ---------------------------------------------------------------------------
# 2. Behavioural: neither script hangs with stdin closed
# ---------------------------------------------------------------------------
echo "TEST 2: scripts terminate with stdin closed..."

# `bash -n` parses without executing, so this is safe to run against the real
# scripts; it proves no syntax error hides an unreachable guard.
for s in install.sh uninstall.sh; do
    if bash -n "$REPO_ROOT/$s" 2>/dev/null; then
        pass "$s: parses cleanly"
    else
        fail "$s: syntax error"
    fi
done

# Drive the actual legacy-key prompt block in isolation with stdin closed. If
# it blocks, the subshell never returns and the timeout trips.
probe_key_prompt() {
    local tmp; tmp="$(mktemp -d)"
    local key="$tmp/claude-usage-key.json"
    printf '{"sessionKey":"sk-test"}' > "$key"

    # Extract the block verbatim from install.sh so the test tracks the real
    # code rather than a copy that can drift.
    local block
    block="$(awk '/^_legacy_key=/,/^fi$/' "$REPO_ROOT/install.sh")"
    if [ -z "$block" ]; then
        fail "could not locate the legacy-key block in install.sh"
        rm -rf "$tmp"
        return
    fi

    local runner="$tmp/run.sh"
    {
        echo 'info() { printf "[i] %s\n" "$1"; }'
        echo 'warn() { printf "[w] %s\n" "$1"; }'
        echo 'ok()   { printf "[+] %s\n" "$1"; }'
        echo "CONFIG_DIR='$tmp'"
        echo "$block"
    } > "$runner"

    local out rc
    out="$(timeout 5 bash "$runner" < /dev/null 2>&1)"; rc=$?

    if [ "$rc" -eq 124 ]; then
        fail "legacy-key prompt BLOCKS with stdin closed (would hang installs)"
    elif [ "$rc" -ne 0 ]; then
        fail "legacy-key block exited $rc with stdin closed"
    elif ! printf '%s' "$out" | grep -q 'Non-interactive'; then
        fail "legacy-key block took the interactive path with no TTY"
    elif [ ! -f "$key" ]; then
        fail "legacy-key block deleted a credential without being asked"
    else
        pass "legacy-key prompt: skips cleanly, keeps the key, no hang"
    fi
    rm -rf "$tmp"
}
probe_key_prompt

echo ""
if [ "$FAILED" -eq 0 ]; then
    echo "All non-interactive install checks passed."
else
    echo "Non-interactive install checks FAILED."
fi
exit "$FAILED"
