#!/usr/bin/env bash
# test_install_dir.sh — install.sh must deploy from the checkout it is run from,
# never a stale managed clone elsewhere.
#
# Regression for the footgun where a plain `./install.sh` from a working tree
# silently re-pointed the live ~/.local/bin symlinks at $HOME/projects/tmux-status
# and rebuilt the render daemon venv from that (older) clone's source.
#
# The resolve_install_dir() function is extracted from install.sh and exercised
# directly, so the test and the installer can never drift. Portable to bash 3.2.

set -u

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
INSTALL_SH="$REPO_ROOT/install.sh"

fail() { echo "FAIL: $1"; exit 1; }

# Pull the resolver out of install.sh (header line through its closing brace).
fn="$(awk '/^resolve_install_dir\(\) \{/{f=1} f{print} f&&/^}$/{exit}' "$INSTALL_SH")"
[ -n "$fn" ] || fail "could not extract resolve_install_dir from install.sh"
eval "$fn"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
HOME="$TMP/home"; mkdir -p "$HOME"   # the function reads $HOME for its fallback

# A real checkout fixture has both markers the resolver looks for.
CHECKOUT="$TMP/checkout"; mkdir -p "$CHECKOUT/overlay" "$CHECKOUT/server"
: > "$CHECKOUT/overlay/status.conf"

# 1) Run from a real checkout, no override -> install from THAT checkout.
unset TMUX_STATUS_DIR
got="$(resolve_install_dir "$CHECKOUT")"
[ "$got" = "$CHECKOUT" ] || fail "checkout default: got '$got', want '$CHECKOUT'"

# 2) TMUX_STATUS_DIR override always wins, even from a checkout.
TMUX_STATUS_DIR="/explicit/dir"
got="$(resolve_install_dir "$CHECKOUT")"
[ "$got" = "/explicit/dir" ] || fail "override: got '$got', want '/explicit/dir'"
unset TMUX_STATUS_DIR

# 3) curl | bash (no on-disk script dir) -> the managed ~/projects location.
got="$(resolve_install_dir "")"
[ "$got" = "$HOME/projects/tmux-status" ] || fail "curl|bash fallback: got '$got'"

# 4) A script dir that is NOT a checkout (missing markers) -> fallback, never
#    that bare directory (guards against installing from a non-source tree).
NOTACHECKOUT="$TMP/random"; mkdir -p "$NOTACHECKOUT"
got="$(resolve_install_dir "$NOTACHECKOUT")"
[ "$got" = "$HOME/projects/tmux-status" ] || fail "non-checkout dir: got '$got', want fallback"

# 5) A checkout missing only server/ is not treated as a source tree.
PARTIAL="$TMP/partial"; mkdir -p "$PARTIAL/overlay"; : > "$PARTIAL/overlay/status.conf"
got="$(resolve_install_dir "$PARTIAL")"
[ "$got" = "$HOME/projects/tmux-status" ] || fail "partial checkout: got '$got', want fallback"

echo "✓ test_install_dir.sh passed"
