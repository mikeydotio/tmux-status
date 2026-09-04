#!/usr/bin/env bash
# Regression: uninstall.sh removes only the environments created by install.sh,
# reports real failures, and never delegates to an unrelated system pip.

set -u

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
UNINSTALL_SH="$REPO_ROOT/uninstall.sh"
FAILED=0

pass() { printf '  \033[1;32mPASS\033[0m  %s\n' "$1"; }
fail() { printf '  \033[1;31mFAIL\033[0m  %s\n' "$1"; FAILED=1; }
info() { :; }
error() { printf 'ERROR: %s\n' "$1" >&2; }

fn="$(awk '/^cleanup_server_environments\(\) \{/{f=1} f{print} f&&/^}$/{exit}' "$UNINSTALL_SH")"
if [ -z "$fn" ]; then
    fail "could not extract cleanup_server_environments from uninstall.sh"
else
    eval "$fn"
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
FAKE_BIN="$WORK/bin"
FAKE_PIPX_HOME="$WORK/pipx"
PIPX_LOG="$WORK/pipx.log"
mkdir -p "$FAKE_BIN" "$FAKE_PIPX_HOME/venvs/tmux-status-server"

cat > "$FAKE_BIN/pipx" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$PIPX_LOG"
case "$1" in
    environment)
        printf '%s\n' "$FAKE_PIPX_HOME"
        ;;
    uninstall)
        if [ "${PIPX_FAIL:-0}" -eq 1 ]; then
            exit 7
        fi
        rm -rf "$FAKE_PIPX_HOME/venvs/tmux-status-server"
        ;;
    *)
        exit 2
        ;;
esac
EOF
chmod +x "$FAKE_BIN/pipx"
export FAKE_PIPX_HOME PIPX_LOG
PATH="$FAKE_BIN:/usr/bin:/bin"

FALLBACK="$WORK/fallback"
mkdir -p "$FALLBACK/bin"
: > "$FALLBACK/pyvenv.cfg"
: > "$FALLBACK/bin/tmux-status-server"

if [ -n "$fn" ] && cleanup_server_environments "$FALLBACK"; then
    if [ -d "$FAKE_PIPX_HOME/venvs/tmux-status-server" ] || [ -d "$FALLBACK" ]; then
        fail "managed environments survived cleanup"
    elif ! grep -qx 'uninstall tmux-status-server' "$PIPX_LOG"; then
        fail "pipx environment was not uninstalled by name"
    else
        pass "pipx and fallback environments are removed"
    fi
else
    fail "managed environment cleanup failed"
fi

if [ -n "$fn" ] && cleanup_server_environments "$FALLBACK"; then
    pass "missing managed environments are idempotent"
else
    fail "missing managed environments caused an error"
fi

UNKNOWN="$WORK/unknown"
mkdir -p "$UNKNOWN/bin"
: > "$UNKNOWN/keep"
if [ -n "$fn" ] && cleanup_server_environments "$UNKNOWN" >/dev/null 2>&1; then
    fail "unrecognized fallback directory was accepted"
elif [ ! -f "$UNKNOWN/keep" ]; then
    fail "unrecognized fallback directory was modified"
else
    pass "unrecognized fallback directory is preserved"
fi

mkdir -p "$FAKE_PIPX_HOME/venvs/tmux-status-server"
PIPX_FAIL=1
export PIPX_FAIL
if [ -n "$fn" ] && cleanup_server_environments "$WORK/absent" >/dev/null 2>&1; then
    fail "pipx uninstall failure was swallowed"
elif [ ! -d "$FAKE_PIPX_HOME/venvs/tmux-status-server" ]; then
    fail "failed pipx environment was removed unexpectedly"
else
    pass "pipx uninstall failure is reported and preserved"
fi

if grep -qE '(^|[[:space:]])pip3 uninstall' "$UNINSTALL_SH"; then
    fail "uninstall.sh still mutates the system pip environment"
else
    pass "system pip uninstall path is absent"
fi

if [ "$FAILED" -eq 0 ]; then
    echo "All uninstall environment checks passed."
else
    echo "Uninstall environment checks FAILED."
fi
exit "$FAILED"
