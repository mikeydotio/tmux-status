#!/usr/bin/env bash
# Regression gate: a populated setuptools build/lib package must exactly match
# the source package. A missing build tree is clean because nothing can ship.

set -u

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
FAILED=0

pass() { printf '  \033[1;32mPASS\033[0m  %s\n' "$1"; }
fail() { printf '  \033[1;31mFAIL\033[0m  %s\n' "$1"; FAILED=1; }

compare_python_trees() {
    local source_dir="$1" staged_dir="$2" scratch_dir="$3"

    [ -d "$staged_dir" ] || return 0
    find "$source_dir" -type f -name '*.py' \
        | sed "s|^$source_dir/||" | LC_ALL=C sort > "$scratch_dir/source-files"
    find "$staged_dir" -type f -name '*.py' \
        | sed "s|^$staged_dir/||" | LC_ALL=C sort > "$scratch_dir/staged-files"
    diff -u "$scratch_dir/source-files" "$scratch_dir/staged-files"
}

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
SOURCE="$WORK/source"
STAGED="$WORK/build/lib/tmux_status_server"
mkdir -p "$SOURCE/subpackage" "$STAGED/subpackage"
: > "$SOURCE/__init__.py"
: > "$SOURCE/module.py"
: > "$SOURCE/subpackage/__init__.py"
cp -R "$SOURCE/." "$STAGED/"

if compare_python_trees "$SOURCE" "$STAGED" "$WORK" >/dev/null; then
    pass "matching staged package is accepted"
else
    fail "matching staged package was rejected"
fi

: > "$STAGED/orphan.py"
if compare_python_trees "$SOURCE" "$STAGED" "$WORK" >/dev/null; then
    fail "staged orphan was not detected"
else
    pass "staged orphan is detected"
fi

rm "$STAGED/orphan.py"
LIVE_SOURCE="$REPO_ROOT/server/tmux_status_server"
LIVE_STAGED="$REPO_ROOT/server/build/lib/tmux_status_server"
if compare_python_trees "$LIVE_SOURCE" "$LIVE_STAGED" "$WORK" >/dev/null; then
    pass "live staging tree is absent or matches source"
else
    fail "live staging tree contains stale or missing Python modules"
fi

if [ "$FAILED" -eq 0 ]; then
    echo "All build-artifact checks passed."
else
    echo "Build-artifact checks FAILED."
fi
exit "$FAILED"
