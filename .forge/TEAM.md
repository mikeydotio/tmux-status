# Agent Team Roster

## Project Type
CLI tool / Infrastructure (network service + CLI client integration)

## Active Agents
### Always Active
- domain-researcher
- software-architect
- senior-engineer
- qa-engineer
- project-manager
- devils-advocate
- technical-writer
- generator
- evaluator
- reviewer
- validator
- triager

### Conditionally Activated
- ux-designer: NO — no GUI or web interface. The "UX" is tmux status bar text, which is already designed and won't change.
- security-researcher: YES — the server handles session keys (credentials), serves on a network, and has optional API key auth. Needs threat model review for credential storage, network exposure, and auth bypass.
- accessibility-engineer: NO — output is tmux status bar text with 256-color codes. No assistive technology interface.

## Rationale
- **Security researcher activated** because: (1) server holds a claude.ai session key — a credential that grants account access, (2) server binds to a network interface (0.0.0.0 by default), (3) optional API key auth needs review for bypass risks, (4) client fetches data over HTTP on a LAN/tailnet — need to verify trust assumptions.
- **UX designer skipped** because: the user-facing interface is unchanged tmux status bar segments. The only new "UX" is `settings.conf` configuration (one line: `QUOTA_SOURCE=http://...`), which is trivially simple.
- **Accessibility engineer skipped** because: tmux status bars are inherently visual-only terminal output. There's no feasible assistive technology integration point.
