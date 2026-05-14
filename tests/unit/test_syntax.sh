#!/usr/bin/env bash
# Syntax gate: every bash script in the repo must parse with `bash -n`.
#
# Catches errors like unbalanced quotes inside heredocs that sit inside
# `eval "$(...)"` command substitution, where a stray apostrophe in a
# comment can break the whole script. See commit e5ce852.
#
# Portable to bash 3.2 (macOS default).
set -eu

REPO_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
cd "$REPO_ROOT"

is_bash_script() {
    case "$1" in
        *.sh) return 0 ;;
    esac
    # Read first line; treat unreadable files as not-a-script.
    first=$(head -n 1 -- "$1" 2>/dev/null) || return 1
    case "$first" in
        '#!'*bash*) return 0 ;;
    esac
    return 1
}

found=0
failed=0
while IFS= read -r f; do
    if is_bash_script "$f"; then
        found=$((found + 1))
        if bash -n "$f" 2>/tmp/test_syntax.err; then
            echo "  PASS  $f"
        else
            echo "  FAIL  $f"
            sed 's/^/        /' /tmp/test_syntax.err >&2
            failed=$((failed + 1))
        fi
    fi
done <<EOF
$(find . \
    -path ./.git -prune -o \
    -path './**/venv' -prune -o \
    -path '*/node_modules/*' -prune -o \
    -type f -print | sort -u)
EOF

rm -f /tmp/test_syntax.err

if [ "$found" -eq 0 ]; then
    echo "FAIL: no bash scripts discovered — gate is not protecting anything" >&2
    exit 1
fi

if [ "$failed" -ne 0 ]; then
    echo
    echo "Syntax gate failed: $failed of $found scripts have parse errors." >&2
    echo "Reproduce locally with: bash -n <path>" >&2
    exit 1
fi

echo
echo "All $found bash scripts parsed cleanly."
