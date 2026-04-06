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
SCRIPTS=(tmux-claude-status tmux-git-status tmux-status-apply-config tmux-status-session tmux-status-context-hook.js)
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

# ── Branch check ──────────────────────────────────────────────
# The installer expects the repo to be on 'main'. If the local checkout
# is on a different branch, later steps (e.g. server/ package install)
# will fail because expected files won't exist.
_current_branch=$(git -C "$INSTALL_DIR" branch --show-current 2>/dev/null || echo "unknown")
if [ "$_current_branch" != "main" ]; then
    warn "Local repo is on branch '$_current_branch', not 'main'"
    echo "  The installer expects the 'main' branch. Some files may be missing."
    echo "  To fix:  cd $INSTALL_DIR && git checkout main && git pull"
    echo ""
    if [ -t 0 ]; then
        read -rp "  Continue anyway? [y/N] " _reply
        if [[ ! "$_reply" =~ ^[Yy] ]]; then
            info "Aborted. Switch to 'main' and re-run the installer."
            exit 0
        fi
    else
        warn "Non-interactive mode — continuing, but errors may follow."
    fi
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

# ── Migrate settings.conf for new keys ──────────────────────
_settings="$CONFIG_DIR/settings.conf"
if [ -f "$_settings" ]; then
    _migrated=false
    if ! grep -q '^QUOTA_SOURCE=' "$_settings"; then
        printf '\n# URL of the quota data server (added by installer upgrade)\nQUOTA_SOURCE=http://127.0.0.1:7850\n' >> "$_settings"
        _migrated=true
    fi
    if ! grep -q '^QUOTA_CACHE_TTL=' "$_settings"; then
        printf '\n# Cache TTL in seconds. 0 = always fetch (localhost). 30 = remote.\nQUOTA_CACHE_TTL=0\n' >> "$_settings"
        _migrated=true
    fi
    if grep -q '^TOP_BANNER=' "$_settings" && ! grep -q '^SHOW_TOP_BANNER=' "$_settings"; then
        _val=$(grep '^TOP_BANNER=' "$_settings" | head -1 | cut -d= -f2)
        printf '\n# Migrated from TOP_BANNER (renamed)\nSHOW_TOP_BANNER=%s\n' "$_val" >> "$_settings"
        _migrated=true
    fi
    $_migrated && ok "Migrated settings.conf with new settings"
fi

# ── Add source line to tmux.conf ──────────────────────────────
TMUX_CONF=$(detect_tmux_conf)
info "Configuring $TMUX_CONF..."

if grep -qF "$SOURCE_MARKER" "$TMUX_CONF" 2>/dev/null; then
    info "Source line already present in $TMUX_CONF"
else
    # Ensure file ends with a newline before appending
    [ -s "$TMUX_CONF" ] && [ "$(tail -c1 "$TMUX_CONF" | xxd -p)" != "0a" ] && echo "" >> "$TMUX_CONF"
    cat >> "$TMUX_CONF" << TMUXLINE

# tmux-status: 3-line status bar (https://github.com/mikeydotio/tmux-status)
source-file $INSTALL_DIR/overlay/status.conf
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
if [ ! -d "$INSTALL_DIR/server/" ]; then
    error "server/ directory not found in $INSTALL_DIR"
    echo "  This usually means the repo is on the wrong branch (current: ${_current_branch:-unknown})."
    echo "  To fix:  cd $INSTALL_DIR && git checkout main && git pull"
    exit 1
fi
info "Installing tmux-status-server package..."
_server_installed=false

# Strategy 1: pipx (cleanest — isolated venv, auto-links to ~/.local/bin/)
if command -v pipx >/dev/null 2>&1; then
    if pipx install --force "$INSTALL_DIR/server/" 2>&1; then
        _server_installed=true
        ok "Server package installed (via pipx)"
    else
        warn "pipx install failed, trying fallback..."
    fi
fi

# Strategy 2: dedicated venv with symlink (works on PEP 668 systems)
if ! $_server_installed; then
    VENV_DIR="$HOME/.local/share/tmux-status/venv"
    info "Creating venv at $VENV_DIR..."
    python3 -m venv "$VENV_DIR" 2>&1 && \
    "$VENV_DIR/bin/pip" install "$INSTALL_DIR/server/" 2>&1 && \
    ln -sf "$VENV_DIR/bin/tmux-status-server" "$BIN_DIR/tmux-status-server" && \
    _server_installed=true && \
    ok "Server package installed (venv + symlink)"
fi

if ! $_server_installed; then
    error "Could not install server package."
    echo ""
    echo "  Modern Python (3.12+) blocks system-wide pip install (PEP 668)."
    echo "  Install one of the following, then re-run this installer:"
    echo ""
    echo "    sudo apt install python3-venv    # recommended"
    echo "    sudo apt install pipx             # alternative"
    echo ""
    exit 1
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
    sed -i '' "s|~/.local/bin/tmux-status-server|$HOME/.local/bin/tmux-status-server|g" "$LAUNCHD_PLIST"
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
