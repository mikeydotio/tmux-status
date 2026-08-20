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

# Resolve which source tree to install FROM. Precedence:
#   1. $TMUX_STATUS_DIR            — explicit override, always wins.
#   2. this script's own directory — when it's a real checkout (has the overlay
#      + server/ markers). So running `./install.sh` from a working tree deploys
#      THAT tree, never a stale managed clone elsewhere (the footgun where a
#      plain run silently re-pointed symlinks + rebuilt the daemon from old code).
#   3. $HOME/projects/tmux-status  — the managed location for `curl … | bash`,
#      where the script is piped from stdin and has no on-disk location.
resolve_install_dir() {
    local script_dir="$1"
    if [ -n "${TMUX_STATUS_DIR:-}" ]; then
        printf '%s\n' "$TMUX_STATUS_DIR"
    elif [ -n "$script_dir" ] && [ -f "$script_dir/overlay/status.conf" ] && [ -d "$script_dir/server" ]; then
        printf '%s\n' "$script_dir"
    else
        printf '%s\n' "$HOME/projects/tmux-status"
    fi
}

# A `curl | bash` pipe leaves BASH_SOURCE unset or non-file, so SCRIPT_DIR is
# empty there and resolve_install_dir falls through to the managed location.
_script_src="${BASH_SOURCE[0]:-}"
if [ -n "$_script_src" ] && [ -f "$_script_src" ]; then
    SCRIPT_DIR="$(cd "$(dirname "$_script_src")" >/dev/null 2>&1 && pwd -P)"
else
    SCRIPT_DIR=""
fi
INSTALL_DIR="$(resolve_install_dir "$SCRIPT_DIR")"
BIN_DIR="$HOME/.local/bin"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/tmux-status"
SOURCE_MARKER="tmux-status/overlay/status.conf"

# Scripts to symlink into ~/.local/bin/
# (tmux_claude_model.py is no longer symlinked: the thin readers don't import it
#  and the render daemon uses its own vendored copy inside the server package.)
SCRIPTS=(tmux-agent-status tmux-claude-status tmux-git-status tmux-status-poke tmux-status-apply-config tmux-status-session tmux-status-prune-clients tmux-status-context-hook.js)
CLAUDE_SETTINGS="$HOME/.claude/settings.json"
STATUSLINE_CMD='node "$HOME/.local/bin/tmux-status-context-hook.js"'

# ── Parse flags ───────────────────────────────────────────────
SERVER_MODE=false
SERVER_NO_AUTH=false
SERVER_API_KEY=""
SERVER_PORT=""

while [ $# -gt 0 ]; do
    case "$1" in
        --server)   SERVER_MODE=true; shift ;;
        --no-auth)  SERVER_NO_AUTH=true; shift ;;
        --api-key)  SERVER_API_KEY="${2:-}"; shift 2 ;;
        --port)     SERVER_PORT="${2:-}"; shift 2 ;;
        *)          printf '\033[1;31m[tmux-status]\033[0m Unknown option: %s\n' "$1" >&2; exit 1 ;;
    esac
done

if $SERVER_NO_AUTH && ! $SERVER_MODE; then
    printf '\033[1;31m[tmux-status]\033[0m --no-auth requires --server\n' >&2; exit 1
fi
if [ -n "$SERVER_API_KEY" ] && ! $SERVER_MODE; then
    printf '\033[1;31m[tmux-status]\033[0m --api-key requires --server\n' >&2; exit 1
fi
if $SERVER_NO_AUTH && [ -n "$SERVER_API_KEY" ]; then
    printf '\033[1;31m[tmux-status]\033[0m --no-auth and --api-key are mutually exclusive\n' >&2; exit 1
fi

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
if [ -n "$SCRIPT_DIR" ] && [ "$INSTALL_DIR" = "$SCRIPT_DIR" ]; then
    # Running the installer from inside its own checkout: deploy THIS tree
    # exactly as-is. Don't pull/clone — the user is installing what they have
    # in front of them (deliberate local edits, a feature branch, etc.), and a
    # surprise pull or a stale managed clone must never shadow it.
    info "Installing from this checkout: $INSTALL_DIR"
elif [ -d "$INSTALL_DIR/.git" ]; then
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
# will fail because expected files won't exist. Only meaningful for a git
# checkout — a tarball/source dir without .git has no branch to check.
_current_branch=$(git -C "$INSTALL_DIR" branch --show-current 2>/dev/null || echo "unknown")
if [ -d "$INSTALL_DIR/.git" ] && [ "$_current_branch" != "main" ]; then
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
    if ! grep -q '^QUOTA_MAX_STALE=' "$_settings" && ! grep -q '^# QUOTA_MAX_STALE=' "$_settings"; then
        printf '\n# Max age (seconds) of quota cache before showing stale indicators. 0 = disabled.\nQUOTA_MAX_STALE=300\n' >> "$_settings"
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

# tmux-status: 4-line status bar (https://github.com/mikeydotio/tmux-status)
source-file $INSTALL_DIR/overlay/status.conf
TMUXLINE
    ok "Added source line to $TMUX_CONF"
fi

# ── Reload the running tmux server ─────────────────────────────
# The scripts are symlinks (a `git pull` updates them instantly) but tmux's
# status-format lives in the running server's memory and only refreshes on
# `source-file`. Without this, updating to a release that changed a reader's
# argument contract would leave the live config passing the old argument — the
# exact skew that silently blanked the git line after the fork-free refactor.
# `tmux list-sessions` exits non-zero when no server is running (safe probe —
# and, unlike `tmux info`, its name doesn't collide with this script's info()
# function, so ShellCheck stays quiet); re-sourcing is idempotent (it just
# re-`set -g`s the same options).
if tmux list-sessions >/dev/null 2>&1; then
    if tmux source-file "$TMUX_CONF" >/dev/null 2>&1; then
        ok "Reloaded running tmux config (status-format now current)"
    else
        warn "Could not reload tmux; run manually: tmux source-file $TMUX_CONF"
    fi
else
    info "No running tmux server; config applies on next tmux start"
fi

# ── File-descriptor headroom advisory ─────────────────────────
# tmux runs the status bar's #() jobs via fork()+socketpair() inside the tmux
# SERVER; each in-flight job needs a server fd. macOS's launchd default soft
# RLIMIT_NOFILE is only 256, which a modest number of long-lived clients (e.g.
# abandoned mosh/SSH reconnects) plus status jobs can exhaust — after which tmux
# prints "<'…' didn't start>" in place of status lines. Warn (never block) when
# the running server is on a low limit. Read the SERVER's real limit via
# `tmux run-shell` (a plain /bin/sh child of the server) so an interactive shell
# whose .zshrc raised its own ulimit can't mask the server's actual value.
if tmux list-sessions >/dev/null 2>&1; then
    _fdcap="$(mktemp 2>/dev/null || echo "/tmp/tmux-status-fdcap.$$")"
    _srv_nofile=""
    if tmux run-shell "ulimit -Sn > '$_fdcap' 2>/dev/null" >/dev/null 2>&1; then
        for _ in 1 2 3; do
            _srv_nofile="$(tr -dc '0-9' < "$_fdcap" 2>/dev/null || true)"
            [ -n "$_srv_nofile" ] && break
            sleep 0.2
        done
    fi
    rm -f "$_fdcap" 2>/dev/null || true
    _clients="$(tmux list-clients 2>/dev/null | wc -l | tr -d ' ')"
    if [ -n "$_srv_nofile" ] && [ "$_srv_nofile" -le 1024 ] 2>/dev/null; then
        warn "tmux server open-file limit is low (ulimit -n = $_srv_nofile, ${_clients:-?} client(s) attached)."
        echo "  The status bar's #() jobs consume tmux-server file descriptors; a low"
        echo "  limit plus accumulated clients can make tmux show \"<'…' didn't start>\"."
        echo "  Fix durably by raising the limit BEFORE starting tmux (e.g. in your shell rc):"
        echo "      ulimit -n 8192"
        echo "  then restart the tmux server. Reclaim fds from stale clients any time with:"
        echo "      tmux-status-prune-clients"
    fi
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
d['statusLine'] = {'type': 'command', 'command': 'node \"\$HOME/.local/bin/tmux-status-context-hook.js\"'}
with open(path, 'w') as f:
    json.dump(d, f, indent=2)
    f.write('\n')
" 2>/dev/null && ok "Claude Code statusLine hook configured" || warn "Could not update $CLAUDE_SETTINGS"
    elif echo "$existing_sl" | grep -qF "tmux-status-context-hook"; then
        info "Claude Code statusLine hook already configured"
    elif echo "$existing_sl" | grep -qF "coderig-statusline"; then
        # Legacy hook from coderig — replace with tmux-status hook
        info "Replacing legacy coderig-statusline hook with tmux-status-context-hook..."
        python3 -c "
import json
path = '$CLAUDE_SETTINGS'
d = json.load(open(path))
d['statusLine'] = {'type': 'command', 'command': 'node \"\$HOME/.local/bin/tmux-status-context-hook.js\"'}
with open(path, 'w') as f:
    json.dump(d, f, indent=2)
    f.write('\n')
" 2>/dev/null && ok "Replaced legacy statusLine hook" || warn "Could not update $CLAUDE_SETTINGS"
        # Back up the old coderig-statusline.js if it exists as a regular file
        _legacy_hook="$BIN_DIR/coderig-statusline.js"
        if [ -f "$_legacy_hook" ] && [ ! -L "$_legacy_hook" ]; then
            mv "$_legacy_hook" "${_legacy_hook}.tmux-status.bak"
            info "Backed up legacy $_legacy_hook"
        fi
    else
        warn "Claude Code statusLine already configured with a different command:"
        echo "    $existing_sl"
        echo "  To use tmux-status context tracking, update ~/.claude/settings.json:"
        echo "    \"statusLine\": {\"type\": \"command\", \"command\": \"$STATUSLINE_CMD\"}"
    fi
else
    # No settings.json — create a minimal one
    if [ -d "$HOME/.claude" ]; then
        echo '{"statusLine": {"type": "command", "command": "node \"$HOME/.local/bin/tmux-status-context-hook.js\""}}' | python3 -m json.tool > "$CLAUDE_SETTINGS" 2>/dev/null \
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

# Strategy 2: uv (fast, handles venv creation automatically)
if ! $_server_installed && command -v uv >/dev/null 2>&1; then
    VENV_DIR="$HOME/.local/share/tmux-status/venv"
    info "Creating venv at $VENV_DIR (via uv)..."
    if uv venv --clear "$VENV_DIR" 2>&1 && \
       uv pip install --python "$VENV_DIR/bin/python" "$INSTALL_DIR/server/" 2>&1; then
        ln -sf "$VENV_DIR/bin/tmux-status-server" "$BIN_DIR/tmux-status-server"
        ln -sf "$VENV_DIR/bin/tmux-status-renderd" "$BIN_DIR/tmux-status-renderd"
        _server_installed=true
        ok "Server package installed (uv + venv)"
    else
        warn "uv install failed, trying fallback..."
    fi
fi

# Strategy 3: dedicated venv with symlink (works on PEP 668 systems)
if ! $_server_installed; then
    VENV_DIR="$HOME/.local/share/tmux-status/venv"
    info "Creating venv at $VENV_DIR..."
    python3 -m venv "$VENV_DIR" 2>&1 && \
    "$VENV_DIR/bin/pip" install "$INSTALL_DIR/server/" 2>&1 && \
    ln -sf "$VENV_DIR/bin/tmux-status-server" "$BIN_DIR/tmux-status-server" && \
    ln -sf "$VENV_DIR/bin/tmux-status-renderd" "$BIN_DIR/tmux-status-renderd" && \
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

# ── Server mode: API key + args ──────────────────────────────
API_KEY_FILE="$CONFIG_DIR/quota-api-key"
_server_api_key=""
_server_args=""

if $SERVER_MODE; then
    _server_args="--host 0.0.0.0"
    [ -n "$SERVER_PORT" ] && _server_args="$_server_args --port $SERVER_PORT"

    if ! $SERVER_NO_AUTH; then
        if [ -n "$SERVER_API_KEY" ]; then
            _server_api_key="$SERVER_API_KEY"
            printf '%s' "$_server_api_key" > "$API_KEY_FILE"
            chmod 600 "$API_KEY_FILE"
            ok "API key written to $API_KEY_FILE"
        elif [ -s "$API_KEY_FILE" ]; then
            _server_api_key=$(cat "$API_KEY_FILE")
            info "Using existing API key from $API_KEY_FILE"
        else
            _server_api_key=$(python3 -c "import secrets; print(secrets.token_hex(16))")
            printf '%s' "$_server_api_key" > "$API_KEY_FILE"
            chmod 600 "$API_KEY_FILE"
            ok "Generated API key at $API_KEY_FILE"
        fi
        _server_args="$_server_args --api-key-file $API_KEY_FILE"
    fi
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
    if [ -n "$_server_args" ]; then
        sed -i "s|^ExecStart=%h/.local/bin/tmux-status-server$|ExecStart=%h/.local/bin/tmux-status-server $_server_args|" "$SYSTEMD_UNIT"
    fi
    systemctl --user daemon-reload 2>/dev/null || true
    systemctl --user restart tmux-status-server 2>/dev/null || \
        systemctl --user enable --now tmux-status-server 2>/dev/null || true
    ok "systemd user unit installed and started"
elif [ "$OS_TYPE" = "Darwin" ]; then
    # launchd plist
    LAUNCHD_DIR="$HOME/Library/LaunchAgents"
    LAUNCHD_PLIST="$LAUNCHD_DIR/io.mikey.tmux-status-server.plist"
    mkdir -p "$LAUNCHD_DIR"
    cp "$INSTALL_DIR/server/deploy/io.mikey.tmux-status-server.plist" "$LAUNCHD_PLIST"
    # Expand ~ and inject server args into ProgramArguments
    python3 -c "
import plistlib
path = '$LAUNCHD_PLIST'
with open(path, 'rb') as f:
    pl = plistlib.load(f)
args = ['$HOME/.local/bin/tmux-status-server']
extra = '$_server_args'.split()
if extra:
    args.extend(extra)
pl['ProgramArguments'] = args
with open(path, 'wb') as f:
    plistlib.dump(pl, f)
"
    launchctl unload "$LAUNCHD_PLIST" 2>/dev/null || true
    launchctl load "$LAUNCHD_PLIST" 2>/dev/null || true
    ok "launchd plist installed and loaded"
else
    warn "Unknown OS ($OS_TYPE) — skipping daemon setup"
    echo "  You can run the server manually: tmux-status-server $_server_args"
fi

# ── Install and start the render daemon (systemd/launchd) ─────
# tmux-status-renderd precomputes per-pane status into a cache so the tmux
# status scripts stay fork-free. Takes no arguments (no server-mode injection).
info "Setting up tmux-status-renderd daemon ($OS_TYPE)..."

if [ "$OS_TYPE" = "Linux" ]; then
    RENDERD_SYSTEMD_DIR="$HOME/.config/systemd/user"
    RENDERD_UNIT="$RENDERD_SYSTEMD_DIR/tmux-status-renderd.service"
    mkdir -p "$RENDERD_SYSTEMD_DIR"
    cp "$INSTALL_DIR/server/deploy/tmux-status-renderd.service" "$RENDERD_UNIT"
    systemctl --user daemon-reload 2>/dev/null || true
    systemctl --user restart tmux-status-renderd 2>/dev/null || \
        systemctl --user enable --now tmux-status-renderd 2>/dev/null || true
    ok "render daemon installed and started (systemd)"
elif [ "$OS_TYPE" = "Darwin" ]; then
    RENDERD_LAUNCHD_DIR="$HOME/Library/LaunchAgents"
    RENDERD_PLIST="$RENDERD_LAUNCHD_DIR/io.mikey.tmux-status-renderd.plist"
    mkdir -p "$RENDERD_LAUNCHD_DIR"
    cp "$INSTALL_DIR/server/deploy/io.mikey.tmux-status-renderd.plist" "$RENDERD_PLIST"
    # launchd does not expand ~, so rewrite ProgramArguments to an absolute path
    python3 -c "
import plistlib
path = '$RENDERD_PLIST'
with open(path, 'rb') as f:
    pl = plistlib.load(f)
pl['ProgramArguments'] = ['$HOME/.local/bin/tmux-status-renderd']
with open(path, 'wb') as f:
    plistlib.dump(pl, f)
"
    launchctl unload "$RENDERD_PLIST" 2>/dev/null || true
    launchctl load "$RENDERD_PLIST" 2>/dev/null || true
    ok "render daemon installed and loaded (launchd)"
else
    warn "Unknown OS ($OS_TYPE) — skipping render daemon setup"
    echo "  You can run it manually: tmux-status-renderd"
fi

# ── Schedule the periodic idle-client prune (fork-storm backstop) ─────
# overlay/status.conf prunes on every new client-attach; this timer/agent is the
# backstop for when no new client attaches. It detaches tmux clients idle > 2h
# and reaps their backing mosh-server/sshd-session so abandoned mosh/SSH
# reconnects can't accumulate into a status-bar fork storm. Detach-only +
# allowlisted transport reap — it never kills a session, its work, or a local
# terminal.
info "Scheduling periodic idle-client prune ($OS_TYPE)..."

if [ "$OS_TYPE" = "Linux" ]; then
    PRUNE_SYSTEMD_DIR="$HOME/.config/systemd/user"
    mkdir -p "$PRUNE_SYSTEMD_DIR"
    cp "$INSTALL_DIR/server/deploy/tmux-status-prune.service" "$PRUNE_SYSTEMD_DIR/tmux-status-prune.service"
    cp "$INSTALL_DIR/server/deploy/tmux-status-prune.timer"   "$PRUNE_SYSTEMD_DIR/tmux-status-prune.timer"
    systemctl --user daemon-reload 2>/dev/null || true
    systemctl --user enable --now tmux-status-prune.timer 2>/dev/null || true
    ok "prune timer installed and started (systemd)"
elif [ "$OS_TYPE" = "Darwin" ]; then
    PRUNE_PLIST="$HOME/Library/LaunchAgents/io.mikey.tmux-status-prune.plist"
    mkdir -p "$HOME/Library/LaunchAgents"
    cp "$INSTALL_DIR/server/deploy/io.mikey.tmux-status-prune.plist" "$PRUNE_PLIST"
    # launchd does not expand ~; rewrite the program path to absolute while
    # preserving the --reap-transport / idle-seconds arguments after it.
    python3 -c "
import plistlib
path = '$PRUNE_PLIST'
with open(path, 'rb') as f:
    pl = plistlib.load(f)
pl['ProgramArguments'] = ['$HOME/.local/bin/tmux-status-prune-clients'] + pl['ProgramArguments'][1:]
with open(path, 'wb') as f:
    plistlib.dump(pl, f)
"
    launchctl unload "$PRUNE_PLIST" 2>/dev/null || true
    launchctl load "$PRUNE_PLIST" 2>/dev/null || true
    ok "prune agent installed and loaded (launchd, every 30m)"
else
    warn "Unknown OS ($OS_TYPE) — skipping prune scheduler"
    echo "  You can prune manually any time: tmux-status-prune-clients --reap-transport"
fi

# Warm the per-pane cache so the status bar shows data immediately rather than
# blanking until the daemon's first tick.
if [ -x "$BIN_DIR/tmux-status-renderd" ]; then
    "$BIN_DIR/tmux-status-renderd" --once >/dev/null 2>&1 || true
fi

# ── Done ───────────────────────────────────────────────────────
_port="${SERVER_PORT:-7850}"
echo ""

if $SERVER_MODE; then
    ok "tmux-status installed in SERVER mode!"
    echo ""
    echo "  Quota server listening on 0.0.0.0:$_port"
    if ! $SERVER_NO_AUTH; then
        echo "  API key: $_server_api_key"
        echo "  Key file: $API_KEY_FILE"
    else
        warn "No authentication configured (--no-auth)"
    fi
    echo ""
    echo "  ── Client setup ──"
    echo "  On each client machine, edit ~/.config/tmux-status/settings.conf:"
    echo ""
    echo "    QUOTA_SOURCE=http://<this-server-ip>:$_port"
    if ! $SERVER_NO_AUTH; then
        echo "    QUOTA_API_KEY=$_server_api_key"
    fi
    echo "    QUOTA_CACHE_TTL=30"
    echo ""
    echo "  Ensure port $_port is open in your firewall."
else
    ok "tmux-status installed successfully!"
    echo ""
    echo "  The quota server is running at http://127.0.0.1:$_port"
fi

echo ""
echo "  Check server + render daemon status:"
if [ "$OS_TYPE" = "Linux" ]; then
    echo "    systemctl --user status tmux-status-server tmux-status-renderd"
elif [ "$OS_TYPE" = "Darwin" ]; then
    echo "    launchctl list | grep tmux-status"
else
    echo "    curl -s http://127.0.0.1:$_port/health"
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
