# tmux-status

A 3-line tmux status bar for Claude Code and Codex developers. Shows the active
agent's model, reasoning effort, context, and quota alongside git status and a
clean window bar — without touching your keybindings or preferences.

## Preview

The status bar has three lines, rendered at the bottom of the terminal:

**Line 0** — agent session (only visible when the active pane is running Claude Code or Codex):

```
 Opus 4.6 1M (high) │ Ctx: ▅ 62% │ 3.2h: ▃ 28% │ 5.1d: ▂ 14%
 ╰─ model ──╯ ╰effort╯    ╰context╯    ╰─5h quota─╯   ╰─7d quota─╯
```

Codex uses the same layout and labels each quota window by its reset countdown:

```
 GPT-5.6 Sol (xhigh) │ Ctx: ▂ 21% │ 5.1d: ▂ 14%
```

No provider badge is added; the model name identifies the active agent.

**Line 1** — Filesystem path and git status:

```
 ~/projects/myapp : main (dirty, ↑2)
```

**Line 2** — Window tabs and clock:

```
 [bash] [claude] [codex]                                 「12:30」
 ╰────╯ ╰──────╯ ╰────╯                                  ╰─clock─╯
 inactive active  inactive
```

Each tab's brackets are the same color as the window name they wrap (bright white for the active tab; white, or yellow on unseen activity, for inactive tabs).

### Top Banner (optional)

A bold, centered banner at the top of each pane — the hostname and the current window name — using double-line box-drawing:

```
═════════════════╣ MYHOST · ✧ myapp ╠═════════════════
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
| Active tab   | Bright white (bold) | 15  |
| Inactive tab | White         | 7         |
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
5. Configure the Claude Code statusLine hook for real-time Claude context tracking

Codex needs no hook or configuration changes; the render daemon reads its local
open rollout directly.

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

`./install.sh` installs from the checkout it lives in — clone anywhere and run it
from there. Override the source tree explicitly with `TMUX_STATUS_DIR` (e.g. to
reinstall a clone other than the one the script is in):

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

# Show the "hostname · window-name" banner at the top of each pane (default: true)
SHOW_TOP_BANNER=true

# Banner color — 256-color code (default: 208 = orange)
# TOP_BANNER_COLOR=208

# Optional Codex data directory. Falls back to the daemon's CODEX_HOME, then ~/.codex
# CODEX_HOME=~/.codex
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
    { "name": "codex", "commands": ["codex"] },
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
- Status-right (clock)
- Activity monitoring
- Automatic window naming (with Claude/Codex `✧` prefix detection)
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
- **python3** (used by the background renderer and session launcher)
- **git**
- **node** (used by the Claude Code statusLine hook)

**Optional** (for quota display):
- **claude** — the Claude Code CLI, logged in. The quota server reads usage from
  it directly, so there is no API key or session key to configure.

Works on both **macOS** and **Linux**.

## How It Works

See [Architecture](docs/architecture.md) for the full process-selection, rollout,
cache, and failure-isolation contracts.

The installer adds a single line to the end of your tmux.conf:

```tmux
source-file ~/projects/tmux-status/overlay/status.conf
```

This overlay file sets only status-bar-related tmux options. Scripts are symlinked to `~/.local/bin/`, so running `git pull` in the install directory updates everything without re-running the installer.

### Agent Integration

Line 0 is backed by one provider-neutral per-pane cache. The daemon selects the
nearest Claude or Codex descendant of the pane process (newest start time breaks
equal-depth ties), normalizes its local data, and atomically refreshes the cache.
`tmux-agent-status` only sources that cache and formats it. The historical
`tmux-claude-status` command remains installed as a compatibility alias for tmux
configurations already loaded in memory.

#### Claude Code

Line 0 of the status bar shows Claude Code session metadata. There are three data sources, each independent:

**Model + Effort** (always available):
- The daemon walks the process tree from the tmux pane PID to the running Claude process and reads its live session file (`~/.claude/sessions/<pid>.json`) for the conversation id
- The model comes from the session transcript (`.jsonl`) once it has an assistant reply, **or** from the statusLine hook's bridge file before then — so a freshly started or `/clear`'d session shows its model immediately instead of going blank until you start working
- The **effort** label (`auto`/`high`/`xhigh`/`max`) comes from the statusLine hook's live session value, so it tracks the header — including mid-session Shift+Tab changes — falling back to the last `/effort` command or your `settings.json` default

**Context %** (requires statusLine hook):
- The installer configures a Claude Code `statusLine` hook in `~/.claude/settings.json`
- This hook (`tmux-status-context-hook.js`) writes real-time context window usage **and the model id** to a per-session bridge file under `~/.cache/tmux-status/`, then nudges the daemon
- The status bar reads this bridge file every 5 seconds (the hook only rewrites it and pokes the daemon when a value actually changes)
- Without the hook, context % shows 0%

**Quota bars** (optional, requires setup):
- Quota display shows 5-hour and 7-day utilization, read from the Claude CLI's own `/usage` screen
- The installer runs an HTTP quota server locally at `localhost:7850`; other machines can point at it as clients
- Requires only a logged-in `claude` CLI on the server machine — no session key, no API key
- Without it, quota bars are simply omitted from the display

#### Codex

Codex model and reasoning effort come from the latest `turn_context` in the
active rollout. Context usage combines the latest `task_started` context-window
size with the latest `token_count` total. Quota comes from the general `codex`
rate-limit stream, not a named model-specific limit; the freshest general
snapshot across exact active rollouts is displayed by time remaining as
`<reset>: <bar> <percent>`.

To avoid showing a different session's data, the renderer only accepts the exact
rollout JSONL held open by the selected Codex process: `/proc/<pid>/fd` on Linux,
or one batched `lsof` snapshot on macOS. If that identity is unavailable or
ambiguous, Codex line 0 stays blank rather than guessing from recent files.

Set `CODEX_HOME` in `settings.conf` when rollouts live outside the default. The
precedence is settings, the daemon's `CODEX_HOME` environment, then `~/.codex`.
The installer does not install Codex hooks, modify `~/.codex/config.toml`, make
OpenAI API calls, or send Codex quota through the Claude quota server.

When the active pane isn't running either agent, line 0 is empty (a blank spacer line).

### Claude Quota Display Setup (Optional)

Claude's quota system uses an HTTP server that reads usage from the Claude CLI and
serves it to the status bar renderer. The installer sets this up automatically on
`localhost:7850`. Codex quota never uses this server.

#### 1. Log in to the Claude CLI (server machine only)

```bash
claude auth   # or just run `claude` once and sign in
```

Use a Claude Pro, Max, Team, or Enterprise subscription login. Every ~300s the
server boots `claude` headless inside its own private tmux socket, opens `/usage`,
reads the numbers, and tears the session down. It uses the CLI's stored login, so
there is **no session key to mint, rotate, or have silently revoked**.

The collector removes ambient API credentials and provider selectors from the
capture command. This prevents shell startup files from silently replacing the
subscription login with an account that has no five-hour or weekly windows. It
preserves `CLAUDE_CONFIG_DIR`, so a deliberately selected Claude profile remains
selected. If you intentionally need the capture to inherit ambient authentication,
re-run the installer with `--usage-inherit-auth-env`; accounts without subscription
windows will correctly render `X` and report `usage_no_limit_windows`.

The capture is isolated on purpose: it never touches your default tmux server, so
it cannot appear in your window list, consume your tmux server's file descriptors,
or be reaped by `tmux-status-prune-clients`.

#### 2. Verify

```bash
curl -s http://127.0.0.1:7850/health   # {"status":"ok",...}
curl -s http://127.0.0.1:7850/quota    # quota JSON with five_hour/seven_day
```

The server runs as a systemd user unit (Linux) or launchd agent (macOS). A second
daemon, `tmux-status-renderd`, precomputes the per-pane status into a cache so the
tmux status scripts stay fork-free (they only read the cache):

```bash
# Linux
systemctl --user status tmux-status-server tmux-status-renderd
# macOS
launchctl list | grep tmux-status
```

The daemon refreshes on a ~5s cadence. To avoid a blank cold start on a brand-new
pane or a freshly `/clear`'d session, structural tmux events (new window/pane/session)
and the Claude statusLine context hook nudge the daemon (`tmux-status-poke` → SIGUSR1)
for an immediate one-off tick, so the status fills in sub-second. These pokes fire only
on infrequent events — never on the per-render path — so the fork-free guarantee holds
and the steady 5s interval is unchanged.

#### Client Mode (multiple machines)

To show quota on machines without a logged-in Claude CLI, point them at a central server. On each **client** machine, edit `~/.config/tmux-status/settings.conf`:

```bash
QUOTA_SOURCE=http://<server-ip>:7850
QUOTA_API_KEY=my-secret-key        # if server requires auth
QUOTA_CACHE_TTL=30                 # seconds; reduces requests over network
```

Clients don't need the Claude CLI — they only need `tmux-status` installed. Note the served numbers reflect the **server machine's** Claude login.

On the **server** machine, re-run the installer with `--server`:

```bash
./install.sh --server
```

This binds to `0.0.0.0`, auto-generates an API key, and prints the client config snippet. Options:

| Flag | Effect |
|------|--------|
| `--server` | Bind to all interfaces (required) |
| `--no-auth` | Skip API key (trusted LAN) |
| `--api-key <key>` | Use a specific key instead of auto-generating |
| `--port <port>` | Use a custom port (default: 7850) |
| `--usage-inherit-auth-env` | Let ambient credentials override the subscription login |

Re-running `--server` is idempotent — it keeps the existing API key unless `--api-key` provides a new one.

## Update

```bash
cd ~/projects/tmux-status && git pull
```

Scripts update automatically via symlinks. Reload tmux config to pick up any overlay changes.

## Troubleshooting

### Claude quota shows `X`

Inspect `/quota` for the collector error and the daemon log for its marker summary:

```bash
curl -s http://127.0.0.1:7850/quota
tail -n 100 ~/Library/Logs/tmux-status/io.mikey.tmux-status-server.log  # macOS
journalctl --user -u tmux-status-server -n 100                          # Linux
```

On macOS, render-daemon and prune-agent logs use the same directory with file
names matching their launchd labels.

| Error | Meaning |
|---|---|
| `cli_not_found` / `tmux_unavailable` | Required executable is unavailable |
| `cli_boot_timeout` | Claude never became ready |
| `cli_not_authenticated` | The selected profile needs `/login` |
| `cli_workspace_untrusted` | The capture directory needs explicit trust or `--usage-cwd` |
| `usage_screen_timeout` | `/usage` never opened |
| `usage_no_limit_windows` | `/usage` opened, but the selected account exposes no subscription windows |
| `usage_parse_failed` | Limit headings appeared but their values could not be parsed |
| `collector_crashed` | An unexpected collector failure occurred; inspect the log |

### Status lines show `<'…tmux-agent-status "…" model' didn't start>`

That message is printed by **tmux itself**, not by tmux-status. tmux renders the
status bar's `#()` segments by `fork()`-ing a child and creating a
`socketpair()` **inside the tmux server process** — when it can't (it has run
out of file descriptors), it substitutes `<'CMD' didn't start>` for that line.

The usual cause on macOS is the file-descriptor budget. The launchd default soft
limit is only **256 fds**, and *every attached client holds a server fd for as
long as it lives* — including abandoned `mosh`/SSH reconnects that never
detached. They accumulate over days until a status redraw can't get a
socketpair, and the `#()` lines blank out (the bottom, non-`#()` line keeps
rendering).

**Reclaim fds now** — detach idle clients (this never kills your session,
windows, or any process; a client can re-attach at any time):

```bash
tmux-status-prune-clients --dry-run   # preview which idle clients would detach
tmux-status-prune-clients             # detach clients idle > 6h (default)
tmux-status-prune-clients 3600        # or: detach clients idle > 1h
```

**Fix it durably** — give the tmux server a generous fd budget. Because a server
inherits the limit of whatever shell started it, raise it in your shell rc
*before* tmux starts, then restart the server:

```bash
ulimit -n 8192    # in ~/.zshrc / ~/.bashrc, before any `tmux` invocation
```

Sessions you create with `tmux-status-session` already raise this automatically.
Check a running server's real limit (a pane shell's `ulimit -n` can be inflated
by your rc, so ask the server directly):

```bash
tmux run-shell "ulimit -Sn > /tmp/n; :" ; cat /tmp/n
```

## License

MIT
