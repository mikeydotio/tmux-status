# Symptom Report

## Observed Behavior
Some tmux status lines fail to render. The screenshot shows tmux's own
placeholder text in place of the status content:

```
<'~/.local/bin/tmux-claude-status "76272" model' didn't start>
<'~/.local/bin/tmux-claude-status "76272" quota' didn't start>
<'~/.local/bin/tmux-git-status "76272"' didn't start>
```

Line 3 (the native tmux status: `Psamathe: Lillist Moshtail ROH zsh  11:12`)
renders fine — only the three `#()`-driven lines (0/1/2) fail.

## Expected Behavior
Lines 0–2 render the Claude model/context, quota/cost, and git/path segments
(or render empty when the pane isn't running Claude). No `<'…' didn't start>`
placeholders.

## Classification
Intermittent / environmental, worsening over time ("relatively new").

## Timeline
- First noticed: recently; described as a relatively new phenomenon.
- Suspected trigger (user hypothesis): race condition / fork-bomb in the
  render daemon + thin-reader pipeline.
- Frequency: high rate, intermittent (per redraw).

## Reproduction
Occurs on the user's live machine. Not deterministic — appears during status
redraws. Affects multiple panes/lines at once.

## Scope
The `#()` status lines on the long-lived tmux server. The native line 3 is
unaffected.

## Key Observations
- `didn't start` is tmux's literal message when a `#()` format job's
  `job_run()` returns NULL — i.e. tmux could not create the child's
  `socketpair()` or `fork()`.
- User runs mosh-over-Tailscale; many remote sessions.

## Relevant Code Areas
- `overlay/status.conf` (`#()` status-format lines + set-hooks)
- `scripts/tmux-claude-status`, `scripts/tmux-git-status` (thin readers)
- `server/tmux_status_server/render.py` (render daemon)
- `scripts/tmux-status-poke` (daemon wake)
