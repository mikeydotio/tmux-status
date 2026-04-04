# Handoff: review -> triage

## Summary
Static analysis complete. 9 findings: 2 Critical, 4 Important, 3 Useful.

## Key Findings
1. **Critical: Status code mismatch** — Server sends `session_key_expired`, renderer checks for `expired`. Red color indicator broken.
2. **Critical: Dockerfile runs as root** — No USER directive, container process runs as root.
3. **Important: Shell injection surface** — `$pidfile` interpolated into Python string literal in polyglot script.
4. **Important: Context hook non-atomic writes** — Uses writeFileSync instead of temp+rename.
5. **Important: Legacy scripts still symlinked** — Deprecated scripts still deployed by install.sh.
6. **Important: Old fetch script exposes raw exceptions** — str(e) in bridge file error field.

## Design Alignment
MINOR DRIFT — status code naming, deprecated scripts still deployed, context hook atomic writes.

## Context for Next Step
Triage should prioritize the status code mismatch (Critical, functional regression) and Dockerfile root user (Critical, security). The remaining findings are quality improvements.
