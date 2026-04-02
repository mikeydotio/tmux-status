#!/usr/bin/env bash
# tmux-status installer
# https://github.com/mikeydotio/tmux-status
#
# One-line install:
#   curl -fsSL https://raw.githubusercontent.com/mikeydotio/tmux-status/main/install.sh | bash
#
# Or clone first, then run:
#   git clone https://github.com/mikeydotio/tmux-status.git ~/projects/tmux-status
#   ~/projects/tmux-status/install.sh

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────
REPO_URL="https://github.com/mikeydotio/tmux-status.git"
INSTALL_DIR="${TMUX_STATUS_DIR:-$HOME/projects/tmux-status}"
BIN_DIR="$HOME/.local/bin"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/tmux-status"
SOURCE_MARKER="tmux-status/overlay/status.conf"

# Scripts to symlink into ~/.local/bin/
SCRIPTS=(tmux-claude-status tmux-git-status tmux-status-apply-config tmux-status-session)

# ── Helpers ────────────────────────────────────────────────────
info()  { printf '\033[1;34m[tmux-status]\033[0m %s\n' "$1"; }
warn()  { printf '\033[1;33m[tmux-status]\033[0m %s\n' "$1"; }
error() { printf '\033[1;31m[tmux-status]\033[0m %s\n' "$1" >&2; }
ok()    { printf '\033[1;32m[tmux-status]\033[0m %s\n' "$1"; }

check_dep() {
    if ! command -v "$1" >/dev/null 2>&1; then
        error "$1 is required but not found."
        case "$1" in
            python3)
                echo "  macOS:  xcode-select --install  or  brew install python3"
                echo "  Linux:  sudo apt install python3  or  sudo dnf install python3" ;;
            tmux)
                echo "  macOS:  brew install tmux"
                echo "  Linux:  sudo apt install tmux  or  sudo dnf install tmux" ;;
            git)
                echo "  macOS:  xcode-select --install  or  brew install git"
                echo "  Linux:  sudo apt install git  or  sudo dnf install git" ;;
        esac
        return 1
    fi
}

check_tmux_version() {
    local version required="3.2"
    version=$(tmux -V | sed 's/[^0-9.]//g')
    if [ "$(printf '%s\n' "$required" "$version" | sort -V | head -1)" != "$required" ]; then
        error "tmux $required+ required (found $version)"
        return 1
    fi
}

# Detect which tmux.conf to use
detect_tmux_conf() {
    if [ -f "$HOME/.config/tmux/tmux.conf" ]; then
        echo "$HOME/.config/tmux/tmux.conf"
    elif [ -f "$HOME/.tmux.conf" ]; then
        echo "$HOME/.tmux.conf"
    else
        # Create XDG location (modern convention)
        mkdir -p "$HOME/.config/tmux"
        touch "$HOME/.config/tmux/tmux.conf"
        echo "$HOME/.config/tmux/tmux.conf"
    fi
}

# ── Dependency checks ──────────────────────────────────────────
info "Checking dependencies..."
deps_ok=true
for dep in bash git python3 tmux; do
    check_dep "$dep" || deps_ok=false
done
$deps_ok || exit 1
check_tmux_version || exit 1
ok "All dependencies satisfied (tmux $(tmux -V | sed 's/[^0-9.]//g'), python3, git)"

# ── Clone or update repo ──────────────────────────────────────
if [ -d "$INSTALL_DIR/.git" ]; then
    info "Updating existing installation at $INSTALL_DIR..."
    git -C "$INSTALL_DIR" pull --ff-only || {
        warn "Could not fast-forward. Run 'cd $INSTALL_DIR && git pull' manually."
    }
else
    info "Cloning tmux-status to $INSTALL_DIR..."
    mkdir -p "$(dirname "$INSTALL_DIR")"
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

# ── Install scripts to ~/.local/bin/ ───────────────────────────
mkdir -p "$BIN_DIR"
info "Symlinking scripts to $BIN_DIR..."

for script in "${SCRIPTS[@]}"; do
    src="$INSTALL_DIR/scripts/$script"
    dst="$BIN_DIR/$script"

    if [ ! -f "$src" ]; then
        warn "Script not found: $src (skipping)"
        continue
    fi

    if [ -L "$dst" ]; then
        # Existing symlink — check if it points to us
        existing_target=$(ls -l "$dst" | sed 's/.*-> //')
        if [ "$existing_target" = "$src" ]; then
            # Already ours, nothing to do
            continue
        fi
        # Points elsewhere — back up and replace
        warn "Replacing symlink $dst (was → $existing_target)"
        mv "$dst" "${dst}.tmux-status.bak"
    elif [ -f "$dst" ]; then
        # Regular file — back up and replace
        warn "Backing up existing $dst to ${dst}.tmux-status.bak"
        mv "$dst" "${dst}.tmux-status.bak"
    fi

    ln -s "$src" "$dst"
done
ok "Scripts installed"

# ── Install config files ──────────────────────────────────────
mkdir -p "$CONFIG_DIR"
info "Setting up config at $CONFIG_DIR..."

for example_file in "$INSTALL_DIR"/config/*.example.*; do
    [ -f "$example_file" ] || continue
    base=$(basename "$example_file")
    # Remove .example from the name: settings.example.conf → settings.conf
    target_name=$(echo "$base" | sed 's/\.example//')
    target="$CONFIG_DIR/$target_name"

    if [ -f "$target" ]; then
        info "Config already exists, skipping: $target_name"
    else
        cp "$example_file" "$target"
        ok "Created $target_name"
    fi
done

# ── Add source line to tmux.conf ──────────────────────────────
TMUX_CONF=$(detect_tmux_conf)
info "Configuring $TMUX_CONF..."

if grep -qF "$SOURCE_MARKER" "$TMUX_CONF" 2>/dev/null; then
    info "Source line already present in $TMUX_CONF"
else
    # Ensure file ends with a newline before appending
    [ -s "$TMUX_CONF" ] && [ "$(tail -c1 "$TMUX_CONF" | xxd -p)" != "0a" ] && echo "" >> "$TMUX_CONF"
    cat >> "$TMUX_CONF" << 'TMUXLINE'

# tmux-status: 3-line status bar (https://github.com/mikeydotio/tmux-status)
source-file ~/projects/tmux-status/overlay/status.conf
TMUXLINE
    ok "Added source line to $TMUX_CONF"
fi

# ── PATH check ─────────────────────────────────────────────────
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
        warn "$BIN_DIR is not in your PATH"
        echo "  Add to your shell rc file:"
        echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
        echo ""
        echo "  For the status bar itself, this is not required (scripts are"
        echo "  called with full paths). But tmux-status-session needs PATH."
        ;;
esac

# ── Done ───────────────────────────────────────────────────────
echo ""
ok "tmux-status installed successfully!"
echo ""
echo "  Reload tmux config:"
echo "    tmux source-file $TMUX_CONF"
echo ""
echo "  Edit settings:"
echo "    \$EDITOR $CONFIG_DIR/settings.conf"
echo ""
echo "  Create a session with auto-start windows:"
echo "    cp $CONFIG_DIR/windows.example.json $CONFIG_DIR/windows.json"
echo "    \$EDITOR $CONFIG_DIR/windows.json"
echo "    tmux-status-session"
echo ""
echo "  Update later:"
echo "    cd $INSTALL_DIR && git pull"
