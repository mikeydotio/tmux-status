#!/usr/bin/env bash
# tmux-status uninstaller
# https://github.com/mikeydotio/tmux-status
#
# Usage:
#   ~/projects/tmux-status/uninstall.sh
# Or:
#   curl -fsSL https://raw.githubusercontent.com/mikeydotio/tmux-status/main/uninstall.sh | bash

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────
INSTALL_DIR="${TMUX_STATUS_DIR:-$HOME/projects/tmux-status}"
BIN_DIR="$HOME/.local/bin"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/tmux-status"
SOURCE_MARKER="tmux-status/overlay/status.conf"
COMMENT_MARKER="tmux-status: 3-line status bar"

# Scripts that were symlinked
SCRIPTS=(tmux-claude-status tmux-git-status tmux-status-apply-config tmux-status-session tmux-status-context-hook.js tmux-status-quota-fetch tmux-status-quota-poll)
CLAUDE_SETTINGS="$HOME/.claude/settings.json"

# ── Helpers ────────────────────────────────────────────────────
info()  { printf '\033[1;34m[tmux-status]\033[0m %s\n' "$1"; }
warn()  { printf '\033[1;33m[tmux-status]\033[0m %s\n' "$1"; }
ok()    { printf '\033[1;32m[tmux-status]\033[0m %s\n' "$1"; }

# Check if stdin is a terminal (interactive mode)
is_interactive() {
    [ -t 0 ]
}

# Prompt user; default to "no" in non-interactive mode
ask_yn() {
    local prompt="$1"
    if ! is_interactive; then
        return 1  # default no in pipe mode
    fi
    printf '%s [y/N] ' "$prompt"
    read -r answer
    case "$answer" in
        [yY]|[yY][eE][sS]) return 0 ;;
        *) return 1 ;;
    esac
}

# Detect which tmux.conf is in use
detect_tmux_conf() {
    if [ -f "$HOME/.config/tmux/tmux.conf" ] && grep -qF "$SOURCE_MARKER" "$HOME/.config/tmux/tmux.conf" 2>/dev/null; then
        echo "$HOME/.config/tmux/tmux.conf"
    elif [ -f "$HOME/.tmux.conf" ] && grep -qF "$SOURCE_MARKER" "$HOME/.tmux.conf" 2>/dev/null; then
        echo "$HOME/.tmux.conf"
    else
        echo ""
    fi
}

# ── Remove source line from tmux.conf ──────────────────────────
TMUX_CONF=$(detect_tmux_conf)
if [ -n "$TMUX_CONF" ]; then
    info "Removing source line from $TMUX_CONF..."
    # Remove the comment line and the source-file line (portable sed via temp file)
    grep -v -F "$COMMENT_MARKER" "$TMUX_CONF" | grep -v -F "$SOURCE_MARKER" > "$TMUX_CONF.tmp"
    mv "$TMUX_CONF.tmp" "$TMUX_CONF"
    ok "Removed source line from $TMUX_CONF"
else
    info "No tmux.conf found with tmux-status source line (already clean)"
fi

# ── Stop and remove daemon (systemd/launchd) ──────────────────
OS_TYPE="$(uname -s)"
info "Stopping tmux-status-server daemon..."

if [ "$OS_TYPE" = "Linux" ]; then
    # systemd user unit
    systemctl --user stop tmux-status-server 2>/dev/null || true
    systemctl --user disable tmux-status-server 2>/dev/null || true
    SYSTEMD_UNIT="$HOME/.config/systemd/user/tmux-status-server.service"
    if [ -f "$SYSTEMD_UNIT" ]; then
        rm "$SYSTEMD_UNIT"
        systemctl --user daemon-reload 2>/dev/null || true
        ok "Removed systemd unit: $SYSTEMD_UNIT"
    else
        info "No systemd unit found (already clean)"
    fi
elif [ "$OS_TYPE" = "Darwin" ]; then
    # launchd plist
    LAUNCHD_PLIST="$HOME/Library/LaunchAgents/io.mikey.tmux-status-server.plist"
    if [ -f "$LAUNCHD_PLIST" ]; then
        launchctl unload "$LAUNCHD_PLIST" 2>/dev/null || true
        rm "$LAUNCHD_PLIST"
        ok "Removed launchd plist: $LAUNCHD_PLIST"
    else
        info "No launchd plist found (already clean)"
    fi
else
    warn "Unknown OS ($OS_TYPE) — skipping daemon teardown"
fi

# ── Uninstall server package ──────────────────────────────────
info "Uninstalling tmux-status-server package..."
pip3 uninstall -y tmux-status-server 2>/dev/null || true
ok "Server package uninstall complete"

# ── Remove symlinks from ~/.local/bin/ ─────────────────────────
info "Removing symlinks from $BIN_DIR..."
for script in "${SCRIPTS[@]}"; do
    dst="$BIN_DIR/$script"

    if [ -L "$dst" ]; then
        # Only remove if it points into our install directory
        existing_target=$(ls -l "$dst" | sed 's/.*-> //')
        case "$existing_target" in
            "$INSTALL_DIR"*)
                rm "$dst"
                # Restore backup if one exists
                if [ -f "${dst}.tmux-status.bak" ]; then
                    mv "${dst}.tmux-status.bak" "$dst"
                    info "Restored backup: $dst"
                fi
                ;;
            *)
                warn "Skipping $dst (symlink points to $existing_target, not tmux-status)"
                ;;
        esac
    elif [ -f "$dst" ]; then
        warn "Skipping $dst (regular file, not a tmux-status symlink)"
    fi
done
ok "Symlinks removed"

# ── Remove Claude Code statusLine hook ─────────────────────────
if [ -f "$CLAUDE_SETTINGS" ]; then
    existing_sl=$(python3 -c "
import json
try:
    d = json.load(open('$CLAUDE_SETTINGS'))
    print(d.get('statusLine', {}).get('command', ''))
except: pass
" 2>/dev/null)
    if echo "$existing_sl" | grep -qF "tmux-status-context-hook"; then
        info "Removing Claude Code statusLine hook..."
        python3 -c "
import json
path = '$CLAUDE_SETTINGS'
d = json.load(open(path))
d.pop('statusLine', None)
with open(path, 'w') as f:
    json.dump(d, f, indent=2)
    f.write('\n')
" 2>/dev/null && ok "Claude Code statusLine hook removed" || warn "Could not update $CLAUDE_SETTINGS"
    fi
fi

# ── Clean up cache directory ──────────────────────────────────
CACHE_DIR="$HOME/.cache/tmux-status"
if [ -d "$CACHE_DIR" ]; then
    if ask_yn "Remove cache at $CACHE_DIR?"; then
        rm -rf "$CACHE_DIR"
        ok "Cache removed"
    else
        info "Cache preserved at $CACHE_DIR"
    fi
fi

# ── Optional: remove config directory ──────────────────────────
if [ -d "$CONFIG_DIR" ]; then
    if ask_yn "Remove configuration at $CONFIG_DIR?"; then
        rm -rf "$CONFIG_DIR"
        ok "Config removed"
    else
        info "Configuration preserved at $CONFIG_DIR"
    fi
fi

# ── Optional: remove cloned repo ──────────────────────────────
if [ -d "$INSTALL_DIR" ]; then
    if ask_yn "Remove cloned repository at $INSTALL_DIR?"; then
        rm -rf "$INSTALL_DIR"
        ok "Repository removed"
    else
        info "Repository preserved at $INSTALL_DIR"
    fi
fi

# ── Done ───────────────────────────────────────────────────────
echo ""
ok "tmux-status uninstalled."
echo ""
echo "  Reload tmux config to restore defaults:"
if [ -n "$TMUX_CONF" ]; then
    echo "    tmux source-file $TMUX_CONF"
else
    echo "    tmux source-file ~/.config/tmux/tmux.conf"
fi
