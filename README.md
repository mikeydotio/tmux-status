# tmux-status

A 3-line tmux status bar for Claude Code developers. Shows Claude session info, git status, and a clean window bar — without touching your keybindings or preferences.

## Preview

The status bar has three lines, rendered at the bottom of the terminal:

**Line 0** — Claude Code session (only visible when the active pane is running Claude):

```
 Opus 4.6 1M (high) │ Ctx: ▅ 62% │ 3.2h: ▃ 28% │ 5.1d: ▂ 14%
 ╰─ model ──╯ ╰effort╯    ╰context╯    ╰─5h quota─╯   ╰─7d quota─╯
```

**Line 1** — Filesystem path and git status:

```
 ~/projects/myapp : main (dirty, ↑2)
```

**Line 2** — Session bar with hostname, window tabs, and clock:

```
 myhost: │bash│ ┃claude┃ │codex│                        「12:30」
         ╰────╯ ╰──────╯ ╰────╯                        ╰─clock─╯
         inactive active   inactive
```

### Top Banner (optional)

A bold, centered hostname banner at the top of each pane using double-line box-drawing:

```
═══════════════════════╣ MYHOST ╠═══════════════════════
```

Enabled by default. Disable in `settings.conf`:

```bash
SHOW_TOP_BANNER=false
# TOP_BANNER_COLOR=208   # 256-color code (default: orange)
```

Uses `pane-border-status top` with `pane-border-lines double`, so enabling the banner also sets `pane-border-style` and `pane-active-border-style` to the banner color. In multi-pane layouts, each pane gets its own banner and the divider borders match.

### Color Reference

Context and quota bars use a color-coded gradient that shifts from cool to warm as usage increases:

| Range    | Bar | Color             | 256-color |
|----------|-----|-------------------|-----------|
| 0–12%    | `_` | Blue              | 34        |
| 13–25%   | `▂` | Green             | 70        |
| 26–37%   | `▃` | Green (brighter)  | 106       |
| 38–50%   | `▄` | Yellow            | 142       |
| 51–62%   | `▅` | Orange            | 178       |
| 63–75%   | `▆` | Orange (brighter) | 214       |
| 76–87%   | `▇` | Red-orange        | 208       |
| 88–100%  | `█` | Red               | 196       |

Segment labels use a pastel palette:

| Segment      | Color         | 256-color |
|--------------|---------------|-----------|
| Model name   | Sky blue      | 117       |
| Context %    | Sage green    | 150       |
| 5h quota     | Light peach   | 223       |
| 7d quota     | Soft wheat    | 186       |
| Hostname     | Blue          | 4         |
| Active tab   | Bright blue   | 12/15     |
| Inactive tab | Blue/white    | 4/7       |
| Activity     | Yellow        | 3         |
| Clock        | Blue brackets | 4         |
| Top banner   | Orange        | 208       |

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/mikeydotio/tmux-status/main/install.sh | bash
```

This will:
1. Clone the repo to `~/projects/tmux-status`
2. Symlink scripts to `~/.local/bin/`
3. Create default config at `~/.config/tmux-status/`
4. Add one `source-file` line to your tmux.conf
5. Configure the Claude Code statusLine hook for real-time context tracking

Then reload tmux:

```bash
tmux source-file ~/.config/tmux/tmux.conf
# or, if using the legacy location:
tmux source-file ~/.tmux.conf
```

### Manual Install

```bash
git clone https://github.com/mikeydotio/tmux-status.git ~/projects/tmux-status
cd ~/projects/tmux-status
./install.sh
```

### Custom Install Location

```bash
TMUX_STATUS_DIR=~/my/custom/path ./install.sh
```

## Uninstall

```bash
~/projects/tmux-status/uninstall.sh
```

Removes the source line from your tmux.conf, removes symlinks, and optionally cleans up config and repo directories.

## Configuration

### Settings

Edit `~/.config/tmux-status/settings.conf`:

```bash
# Use 24-hour clock format (default: false)
CLOCK_24H=true

# Show hostname banner at the top of each pane (default: true)
SHOW_TOP_BANNER=true

# Banner color — 256-color code (default: 208 = orange)
# TOP_BANNER_COLOR=208
```

After editing, reload tmux config to apply.

### Session Launcher

Create `~/.config/tmux-status/windows.json` to define auto-start windows:

```json
{
  "session_name": "dev",
  "windows": [
    { "name": "shell", "commands": [] },
    { "name": "claude", "commands": ["claude"] },
    { "name": "server", "commands": ["cd ~/projects/app", "npm run dev"] }
  ]
}
```

Then run:

```bash
tmux-status-session
```

Each window gets a pinned name and runs its commands with staggered timing. If the session already exists, it re-attaches without modification.

Use a custom config file:

```bash
tmux-status-session ~/my-other-windows.json
```

An example file is provided at `~/.config/tmux-status/windows.example.json`.

## What It Sets (and What It Doesn't)

**Sets** (status bar and optional banner):
- 3-line status bar layout and formatting
- Window tab styling (blue borders, yellow activity, bold active)
- Status-left (hostname) and status-right (clock)
- Activity monitoring
- Automatic window naming (with Claude `✧` prefix detection)
- Pane border status/style (only when `SHOW_TOP_BANNER=true`)

**Does NOT touch:**
- Prefix key
- Keybindings (splits, navigation, resize, copy-mode)
- Mouse settings
- Terminal/clipboard settings
- Scroll buffer
- Any personal preferences

The overlay is sourced at the end of your tmux.conf, so it wins on status-bar options while leaving everything else alone.

## Dependencies

**Required:**
- **tmux 3.2+** (multi-line status support)
- **bash**
- **python3** (used by Claude status and session launcher scripts)
- **git**
- **node** (used by the Claude Code statusLine hook)

**Optional** (for quota display):
- **curl_cffi** (`pip3 install curl-cffi`) — needed by the quota fetcher

Works on both **macOS** and **Linux**.

## How It Works

The installer adds a single line to the end of your tmux.conf:

```tmux
source-file ~/projects/tmux-status/overlay/status.conf
```

This overlay file sets only status-bar-related tmux options. Scripts are symlinked to `~/.local/bin/`, so running `git pull` in the install directory updates everything without re-running the installer.

### Claude Code Integration

Line 0 of the status bar shows Claude Code session metadata. There are three data sources, each independent:

**Model + Effort** (always available):
- The script walks the process tree from the tmux pane PID to find a running Claude process
- Reads the session transcript (`.jsonl`) to extract the model name and effort level

**Context %** (requires statusLine hook):
- The installer configures a Claude Code `statusLine` hook in `~/.claude/settings.json`
- This hook (`tmux-status-context-hook.js`) writes real-time context window usage to `~/.cache/tmux-status/`
- The status bar reads this bridge file every 5 seconds
- Without the hook, context % shows 0%

**Quota bars** (optional, requires setup):
- Quota display shows 5-hour and 7-day API utilization from claude.ai
- Requires a session key and the quota polling daemon (see below)
- Without it, quota bars are simply omitted from the display

When the active pane isn't running Claude, line 0 is empty (a blank spacer line).

### Quota Display Setup (Optional)

To enable the 5-hour and 7-day quota bars:

1. **Install curl_cffi** (needed to bypass Cloudflare):
   ```bash
   pip3 install curl-cffi
   ```

2. **Create a session key file** at `~/.config/tmux-status/claude-usage-key.json`:
   ```json
   {"sessionKey": "sk-ant-...", "expiresAt": "2026-05-01T00:00:00Z"}
   ```
   Get your session key from your browser's cookies on claude.ai (the `sessionKey` cookie).

3. **Start the polling daemon**:
   ```bash
   nohup tmux-status-quota-poll > /dev/null 2>&1 &
   ```
   The daemon fetches quota data every 5 minutes (configurable via `QUOTA_REFRESH_PERIOD` in `settings.conf`; set to `0` to disable polling). To run it persistently, add it to your shell rc or a systemd/launchd service.

4. **Test it manually** (one-shot fetch):
   ```bash
   tmux-status-quota-fetch
   cat ~/.cache/tmux-status/claude-quota.json
   ```

## Update

```bash
cd ~/projects/tmux-status && git pull
```

Scripts update automatically via symlinks. Reload tmux config to pick up any overlay changes.

## License

MIT
