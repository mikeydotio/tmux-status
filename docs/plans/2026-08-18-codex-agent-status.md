# Codex-Compatible Agent Status Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Render Claude Code or Codex model, effort, context, quota, and freshness on tmux line 0 without adding work to the cache-only reader path.

**Architecture:** Extend the render daemon with provider-neutral process selection and status records, then adapt Claude's existing sources and Codex's exact open rollout into that record. Serialize `AGENT_*` fields atomically and have one primary shell reader format provider-specific quota labels; retain the Claude-named reader as a compatibility alias.

**Tech Stack:** Python 3.10 standard library, Bash 3.2-compatible shell, tmux formats, unittest, and shell integration tests.

---

### Task 1: Lock Process and Rollout Resolution Contracts

**Files:**
- Modify: `server/tests/test_render.py`
- Modify: `server/tmux_status_server/render.py`

1. Add failing fixtures for parsing PID/PPID/start/command snapshots.
2. Add failing selection tests proving nearest descendant wins and newest start
   breaks ties across Claude and Codex.
3. Add failing Linux `/proc/<pid>/fd` and macOS batched `lsof` tests, including
   missing and multiple rollout paths.
4. Run `cd server/tests && python3 -m unittest test_render` and confirm failure.
5. Implement one process snapshot, candidate selection, rollout path validation,
   and platform-specific descriptor resolution.
6. Re-run the focused suite and commit the process-resolution slice.

### Task 2: Parse Codex Status Into the Normalized Record

**Files:**
- Modify: `server/tests/test_render.py`
- Modify: `server/tmux_status_server/render.py`

1. Add failing rollout fixtures for valid, malformed, truncated, partial, and
   extra-field JSONL records.
2. Assert model/effort extraction, rounded/clamped context, zero/one/two quota
   slots, duration labels, reset countdowns, reached limits, and missing fields.
3. Implement defensive reverse-tail parsing and Codex status normalization.
4. Adapt Claude's existing output into the same record without changing its
   model, effort, thinking, context, or quota precedence.
5. Run `cd server/tests && python3 -m unittest test_render` and commit the
   provider adapter slice.

### Task 3: Normalize Cache and Reader Rendering

**Files:**
- Create: `scripts/tmux-agent-status`
- Modify: `scripts/tmux-claude-status`
- Modify: `scripts/tmux_claude_model.py`
- Modify: `server/tmux_status_server/model.py`
- Modify: `server/tmux_status_server/render.py`
- Modify: `tests/unit/test_tmux_claude_model.py`
- Modify: `tests/integration/test_render_pipeline.sh`

1. Add failing model tests for `gpt-5.6-sol`, GPT Codex variants, and unknown IDs.
2. Add failing cache/render fixtures for byte-compatible Claude output, Codex
   duration/reset quota output, omitted fields, blank non-agent panes, stale
   caches, and legacy reader compatibility.
3. Implement GPT model formatting and `AGENT_*` cache serialization.
4. Move line-0 formatting to the cache-only `tmux-agent-status` reader and make
   the old name source it without process, transcript, Python, or network work.
5. Run model, render, and pipeline tests; commit the cache/reader slice.

### Task 4: Wire Installation, Overlay, Naming, and Documentation

**Files:**
- Modify: `install.sh`
- Modify: `uninstall.sh`
- Modify: `overlay/status.conf`
- Modify: `config/settings.example.conf`
- Modify: `config/windows.example.json`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `server/pyproject.toml`
- Modify: `server/deploy/io.mikey.tmux-status-renderd.plist`
- Modify: `server/deploy/tmux-status-renderd.service`
- Modify: `tests/unit/test_status_conf_contract.sh`
- Modify: `server/tests/test_render_deploy.py`
- Modify: `server/tests/test_validate_cycle5.py`

1. Add failing assertions for both installed reader names, line 0's new reader,
   Claude/Codex automatic naming, and dual-provider package/deploy descriptions.
2. Install/uninstall both names and switch the overlay to `tmux-agent-status`.
3. Add the optional `CODEX_HOME` example and document its precedence.
4. Update examples and architecture text while explicitly documenting that no
   Codex hooks, config mutation, API calls, or Claude-quota routing occur.
5. Run syntax, install, overlay, deploy, and integration tests; commit the
   installation/documentation slice.

### Task 5: Full Verification and Storyhook Completion

**Files:**
- Modify as needed for test fixes only.

1. Run `make test` and fix every regression.
2. Run `make test-server` and fix every regression.
3. Inspect `git diff --check`, `git status --short`, and the final diff summary.
4. Add a Storyhook verification comment, move TS-41 to `done`, and run
   `story handoff --since 2h`.
