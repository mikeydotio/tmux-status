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
    if (!session) return;

    const homeDir = os.homedir();
    const bridgeDir = path.join(homeDir, '.cache', 'tmux-status');
    const bridgePath = path.join(bridgeDir, `claude-ctx-${session}.json`);

    // The model id is in every statusLine payload — including on a fresh or
    // /clear'd session, before any assistant reply. Carrying it in the bridge is
    // what lets the render daemon show the Claude lines immediately instead of
    // waiting for the first assistant message to land in the transcript (the old
    // cause of both Claude lines going blank until work started).
    const model = (data.model && data.model.id) || '';

    // The statusLine payload carries the LIVE session effort (effort.level:
    // low|medium|high|xhigh|max) and thinking toggle — reflecting mid-session
    // Shift+Tab changes immediately. Bridging them lets the render daemon show
    // the real effort instead of a frozen /effort transcript echo. The effort
    // object is absent for models without a reasoning-effort param, so default
    // to '' (the daemon then falls back to the transcript/settings value).
    const effort = (data.effort && data.effort.level) || '';
    const thinking = !!(data.thinking && data.thinking.enabled);

    // Prior bridge: used to carry used_pct when context_window is momentarily
    // absent, and to dedupe — the statusLine hook fires often, but we only want
    // to write + wake the daemon on an actual change or a brand-new session.
    let prev = null;
    try { prev = JSON.parse(fs.readFileSync(bridgePath, 'utf8')); } catch (e) {}

    const ctx = data.context_window;
    let usedPct = prev ? (prev.used_pct || 0) : 0;
    if (ctx) {
      const remaining = ctx.remaining_percentage;
      usedPct = ctx.used_percentage || 0;

      // When autocompact is enabled, normalize to show usage relative to
      // usable context (Claude reserves ~16.5% as an autocompact buffer).
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
    }

    // Dedupe: if the bridge already holds identical values there is nothing new
    // for the daemon to pick up — skip the write AND the poke (no wasteful fork
    // on every idle status render). effort/thinking are part of the comparison
    // so an effort-only change (Shift+Tab) still writes + pokes. A new/`/clear`'d
    // session has no prior file (or different values), so it always writes and
    // pokes — guaranteeing the cold-start nudge that fills the Claude lines in.
    if (prev && (prev.used_pct || 0) === usedPct && (prev.model || '') === model &&
        (prev.effort || '') === effort && !!prev.thinking === thinking) return;

    try {
      fs.mkdirSync(bridgeDir, { recursive: true });
      const tmpPath = bridgePath + '.tmp';
      fs.writeFileSync(tmpPath, JSON.stringify({
        used_pct: usedPct,
        model: model,
        effort: effort,
        thinking: thinking,
        timestamp: Math.floor(Date.now() / 1000)
      }));
      fs.renameSync(tmpPath, bridgePath);
    } catch (e) {}

    // Wake the render daemon so this session's status fills in immediately
    // instead of waiting for the next ~5s tick — the precise trigger for a
    // fresh session and for /clear (which keeps the pane but starts a new
    // session_id). Fire-and-forget: detached, output-discarded, errors
    // swallowed, so the status bar never depends on the poke succeeding.
    try {
      const { spawn } = require('child_process');
      const child = spawn(
        path.join(homeDir, '.local', 'bin', 'tmux-status-poke'),
        [], { detached: true, stdio: 'ignore' }
      );
      child.on('error', () => {});
      child.unref();
    } catch (e) {}
  } catch (e) {}
});
