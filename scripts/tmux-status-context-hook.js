#!/usr/bin/env node
// tmux-status-context-hook.js — Claude Code statusLine hook
//
// Writes context window usage to a bridge file that tmux-claude-status reads.
// Configured in ~/.claude/settings.json as:
//   "statusLine": {"type": "command", "command": "node ~/.local/bin/tmux-status-context-hook.js"}
//
// Claude Code sends a JSON payload on stdin with session_id and context_window
// data on every context window update.

const fs = require('fs');
const path = require('path');
const os = require('os');

let input = '';
const stdinTimeout = setTimeout(() => process.exit(0), 3000);
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => input += chunk);
process.stdin.on('end', () => {
  clearTimeout(stdinTimeout);
  try {
    const data = JSON.parse(input);
    const session = data.session_id || '';
    const ctx = data.context_window;
    if (!session || !ctx) return;

    const remaining = ctx.remaining_percentage;
    let usedPct = ctx.used_percentage || 0;

    // When autocompact is enabled, normalize to show usage relative to
    // usable context (Claude reserves ~16.5% as an autocompact buffer).
    const homeDir = os.homedir();
    let autoCompact = false;
    try {
      const claudeJson = JSON.parse(fs.readFileSync(path.join(homeDir, '.claude.json'), 'utf8'));
      autoCompact = claudeJson.autoCompactEnabled === true;
    } catch (e) {}
    // Env var override trumps the config flag
    try {
      const settings = JSON.parse(fs.readFileSync(path.join(homeDir, '.claude', 'settings.json'), 'utf8'));
      const override = settings.env?.CLAUDE_AUTOCOMPACT_PCT_OVERRIDE;
      if (override === '100') autoCompact = false;
    } catch (e) {}

    if (autoCompact && remaining != null) {
      const BUFFER = 16.5;
      const usableRemaining = Math.max(0, ((remaining - BUFFER) / (100 - BUFFER)) * 100);
      usedPct = Math.max(0, Math.min(100, Math.round(100 - usableRemaining)));
    }

    try {
      const bridgeDir = path.join(homeDir, '.cache', 'tmux-status');
      fs.mkdirSync(bridgeDir, { recursive: true });
      const bridgePath = path.join(bridgeDir, `claude-ctx-${session}.json`);
      fs.writeFileSync(bridgePath, JSON.stringify({
        used_pct: usedPct,
        timestamp: Math.floor(Date.now() / 1000)
      }));
    } catch (e) {}
  } catch (e) {}
});
