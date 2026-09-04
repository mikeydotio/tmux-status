#!/usr/bin/env bash
# Regression: every server install starts from clean build/venv state and the
# resulting package contains exactly the source modules and dependency closure.

set -u

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
INSTALL_SH="$REPO_ROOT/install.sh"
FAILED=0

pass() { printf '  \033[1;32mPASS\033[0m  %s\n' "$1"; }
fail() { printf '  \033[1;31mFAIL\033[0m  %s\n' "$1"; FAILED=1; }
error() { printf 'ERROR: %s\n' "$1" >&2; }

extract_function() {
    awk -v name="$1" \
        '$0 ~ "^" name "\\(\\) \\{" { found=1 } found { print } found && /^}$/ { exit }' \
        "$INSTALL_SH"
}

clean_fn="$(extract_function clean_build_artifacts)"
verify_fn="$(extract_function verify_installed_package)"
if [ -z "$clean_fn" ]; then
    fail "could not extract clean_build_artifacts from install.sh"
else
    eval "$clean_fn"
fi
if [ -z "$verify_fn" ]; then
    fail "could not extract verify_installed_package from install.sh"
else
    eval "$verify_fn"
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
SERVER="$WORK/server"
SOURCE="$SERVER/tmux_status_server"
mkdir -p "$SOURCE" "$SERVER/build/lib/tmux_status_server" "$SERVER/tmux_status_server.egg-info"
: > "$SERVER/pyproject.toml"
: > "$SOURCE/__init__.py"
: > "$SOURCE/module.py"
: > "$SERVER/build/lib/tmux_status_server/orphan.py"
: > "$SERVER/tmux_status_server.egg-info/PKG-INFO"

if [ -n "$clean_fn" ] && clean_build_artifacts "$SERVER"; then
    if [ -e "$SERVER/build" ] || [ -e "$SERVER/tmux_status_server.egg-info" ]; then
        fail "clean_build_artifacts left stale build metadata"
    else
        pass "clean_build_artifacts removes build/ and egg-info"
    fi
else
    fail "clean_build_artifacts rejected a valid package root"
fi

INVALID="$WORK/not-a-package"
mkdir -p "$INVALID/build"
: > "$INVALID/build/keep"
if [ -n "$clean_fn" ] && clean_build_artifacts "$INVALID" >/dev/null 2>&1; then
    fail "clean_build_artifacts accepted an unguarded path"
elif [ ! -f "$INVALID/build/keep" ]; then
    fail "clean_build_artifacts modified an unguarded path"
else
    pass "clean_build_artifacts refuses unguarded paths"
fi

VENV="$WORK/venv"
python3 -m venv --without-pip "$VENV"
SITE="$($VENV/bin/python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
mkdir -p "$SITE/tmux_status_server" "$SITE/tmux_status_server-0.1.0.dist-info" "$SITE/bottle-1.0.dist-info"
cp -R "$SOURCE/." "$SITE/tmux_status_server/"
cat > "$SITE/tmux_status_server-0.1.0.dist-info/METADATA" <<'EOF'
Metadata-Version: 2.1
Name: tmux-status-server
Version: 0.1.0
Requires-Dist: bottle>=0.12.25
EOF
cat > "$SITE/bottle-1.0.dist-info/METADATA" <<'EOF'
Metadata-Version: 2.1
Name: bottle
Version: 1.0
EOF

PYTHON_WRAPPER="$VENV/bin/python"

if [ -n "$verify_fn" ] && verify_installed_package "$PYTHON_WRAPPER" "$SERVER" >/dev/null 2>&1; then
    pass "exact installed package is accepted"
else
    fail "exact installed package was rejected"
fi

: > "$SITE/tmux_status_server/orphan.py"
if [ -n "$verify_fn" ] && verify_installed_package "$PYTHON_WRAPPER" "$SERVER" >/dev/null 2>&1; then
    fail "installed orphan module was not detected"
else
    pass "installed orphan module is detected"
fi
rm "$SITE/tmux_status_server/orphan.py"

mkdir -p "$SITE/curl_cffi-0.1.dist-info"
cat > "$SITE/curl_cffi-0.1.dist-info/METADATA" <<'EOF'
Metadata-Version: 2.1
Name: curl-cffi
Version: 0.1
EOF
if [ -n "$verify_fn" ] && verify_installed_package "$PYTHON_WRAPPER" "$SERVER" >/dev/null 2>&1; then
    fail "unrelated installed distribution was not detected"
else
    pass "unrelated installed distribution is detected"
fi

if grep -qE 'pipx install[[:space:]]+--force' "$INSTALL_SH"; then
    fail "pipx install still reuses its existing environment"
else
    pass "pipx install does not use --force"
fi
if grep -q 'python3 -m venv "$VENV_DIR"' "$INSTALL_SH"; then
    fail "standard venv strategy does not clear its environment"
else
    pass "standard venv strategy clears its environment"
fi

if [ "$FAILED" -eq 0 ]; then
    echo "All install hygiene checks passed."
else
    echo "Install hygiene checks FAILED."
fi
exit "$FAILED"
