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
SCRIPTS=(tmux-claude-status tmux-git-status tmux-status-apply-config tmux-status-session tmux-status-context-hook.js tmux-status-quota-fetch tmux-status-quota-poll)
CLAUDE_SETTINGS="$HOME/.claude/settings.json"
STATUSLINE_CMD='node ~/.local/bin/tmux-status-context-hook.js'

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

# ── Configure Claude Code statusLine hook ─────────────────────
# The statusLine hook provides real-time context window usage data.
# Without it, the context % in the status bar will always show 0%.
info "Configuring Claude Code statusLine hook..."

if [ -f "$CLAUDE_SETTINGS" ]; then
    # Check if a statusLine is already configured
    existing_sl=$(python3 -c "
import json, sys
try:
    d = json.load(open('$CLAUDE_SETTINGS'))
    sl = d.get('statusLine', {})
    print(sl.get('command', ''))
except: pass
" 2>/dev/null)

    if [ -z "$existing_sl" ]; then
        # No statusLine configured — add ours
        python3 -c "
import json
path = '$CLAUDE_SETTINGS'
d = json.load(open(path))
d['statusLine'] = {'type': 'command', 'command': 'node ~/.local/bin/tmux-status-context-hook.js'}
with open(path, 'w') as f:
    json.dump(d, f, indent=2)
    f.write('\n')
" 2>/dev/null && ok "Claude Code statusLine hook configured" || warn "Could not update $CLAUDE_SETTINGS"
    elif echo "$existing_sl" | grep -qF "tmux-status-context-hook"; then
        info "Claude Code statusLine hook already configured"
    else
        warn "Claude Code statusLine already configured with a different command:"
        echo "    $existing_sl"
        echo "  To use tmux-status context tracking, update ~/.claude/settings.json:"
        echo "    \"statusLine\": {\"type\": \"command\", \"command\": \"$STATUSLINE_CMD\"}"
    fi
else
    # No settings.json — create a minimal one
    if [ -d "$HOME/.claude" ]; then
        echo '{"statusLine": {"type": "command", "command": "node ~/.local/bin/tmux-status-context-hook.js"}}' | python3 -m json.tool > "$CLAUDE_SETTINGS" 2>/dev/null \
            && ok "Created $CLAUDE_SETTINGS with statusLine hook" \
            || warn "Could not create $CLAUDE_SETTINGS"
    else
        warn "Claude Code not installed (~/.claude/ not found). Context % will show 0%."
        echo "  After installing Claude Code, add to ~/.claude/settings.json:"
        echo "    \"statusLine\": {\"type\": \"command\", \"command\": \"$STATUSLINE_CMD\"}"
    fi
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

# ── Install server package ────────────────────────────────────
info "Installing tmux-status-server package..."
if pip3 install "$INSTALL_DIR/server/" 2>/dev/null; then
    ok "Server package installed"
else
    warn "pip3 install failed — trying pip..."
    if pip install "$INSTALL_DIR/server/" 2>/dev/null; then
        ok "Server package installed (via pip)"
    else
        error "Could not install server package. Ensure pip3 or pip is available."
        exit 1
    fi
fi

# ── Kill old quota-poll processes ─────────────────────────────
if pgrep -f 'tmux-status-quota-poll' >/dev/null 2>&1; then
    info "Migrating from legacy quota poller to server-based quota..."
    pkill -f 'tmux-status-quota-poll' 2>/dev/null || true
    ok "Stopped old tmux-status-quota-poll processes (replaced by tmux-status-server)"
fi

# ── Install and start daemon (systemd/launchd) ───────────────
OS_TYPE="$(uname -s)"
info "Setting up tmux-status-server daemon ($OS_TYPE)..."

if [ "$OS_TYPE" = "Linux" ]; then
    # systemd user unit
    SYSTEMD_DIR="$HOME/.config/systemd/user"
    SYSTEMD_UNIT="$SYSTEMD_DIR/tmux-status-server.service"
    mkdir -p "$SYSTEMD_DIR"
    cp "$INSTALL_DIR/server/deploy/tmux-status-server.service" "$SYSTEMD_UNIT"
    systemctl --user daemon-reload 2>/dev/null || true
    systemctl --user enable --now tmux-status-server 2>/dev/null || true
    ok "systemd user unit installed and started"
elif [ "$OS_TYPE" = "Darwin" ]; then
    # launchd plist
    LAUNCHD_DIR="$HOME/Library/LaunchAgents"
    LAUNCHD_PLIST="$LAUNCHD_DIR/io.mikey.tmux-status-server.plist"
    mkdir -p "$LAUNCHD_DIR"
    cp "$INSTALL_DIR/server/deploy/io.mikey.tmux-status-server.plist" "$LAUNCHD_PLIST"
    launchctl load "$LAUNCHD_PLIST" 2>/dev/null || true
    ok "launchd plist installed and loaded"
else
    warn "Unknown OS ($OS_TYPE) — skipping daemon setup"
    echo "  You can run the server manually: tmux-status-server"
fi

# ── Done ───────────────────────────────────────────────────────
echo ""
ok "tmux-status installed successfully!"
echo ""
echo "  The quota server is running at http://127.0.0.1:7850"
echo ""
echo "  Check server status:"
if [ "$OS_TYPE" = "Linux" ]; then
    echo "    systemctl --user status tmux-status-server"
elif [ "$OS_TYPE" = "Darwin" ]; then
    echo "    launchctl list | grep tmux-status-server"
else
    echo "    curl -s http://127.0.0.1:7850/health"
fi
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
