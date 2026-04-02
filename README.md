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

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/mikeydotio/tmux-status/main/install.sh | bash
```

This will:
1. Clone the repo to `~/projects/tmux-status`
2. Symlink scripts to `~/.local/bin/`
3. Create default config at `~/.config/tmux-status/`
4. Add one `source-file` line to your tmux.conf

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

**Sets** (status bar only):
- 3-line status bar layout and formatting
- Window tab styling (blue borders, yellow activity, bold active)
- Status-left (hostname) and status-right (clock)
- Activity monitoring
- Automatic window naming (with Claude `✧` prefix detection)

**Does NOT touch:**
- Prefix key
- Keybindings (splits, navigation, resize, copy-mode)
- Mouse settings
- Terminal/clipboard settings
- Scroll buffer
- Any personal preferences

The overlay is sourced at the end of your tmux.conf, so it wins on status-bar options while leaving everything else alone.

## Dependencies

- **tmux 3.2+** (multi-line status support)
- **bash**
- **python3** (used by Claude status script)
- **git**

Works on both **macOS** and **Linux**.

## How It Works

The installer adds a single line to the end of your tmux.conf:

```tmux
source-file ~/projects/tmux-status/overlay/status.conf
```

This overlay file sets only status-bar-related tmux options. Scripts are symlinked to `~/.local/bin/`, so running `git pull` in the install directory updates everything without re-running the installer.

### Claude Code Integration

Line 0 of the status bar shows Claude Code session metadata by:
1. Walking the process tree from the pane PID to find a running Claude process
2. Reading the session transcript (`.jsonl`) to extract model name and effort level
3. Reading bridge files for real-time context usage and API quota data

When the active pane isn't running Claude, line 0 is empty (a blank spacer line).

## Update

```bash
cd ~/projects/tmux-status && git pull
```

Scripts update automatically via symlinks. Reload tmux config to pick up any overlay changes.

## License

MIT
