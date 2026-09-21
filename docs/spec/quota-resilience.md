# Quota resilience

Status: accepted · Story: TS-56 · Supersedes nothing

## Problem

Quota collection is a screen-scrape of the Claude Code TUI. It has failed in two
materially different ways within two weeks, and both produced the *same*
indistinguishable symptom: a bare `X` in the status bar, indefinitely.

| Outage | Trigger | Collector verdict | Duration |
|---|---|---|---|
| 2026-09-08 16:05–19:22 | CLI booted into an unrecognised startup screen; the `shift+tab` readiness marker never appeared | `cli_boot_timeout`, every marker false | 3h 17m |
| 2026-09-16 14:58 → ongoing | Stored subscription credential no longer usable; the CLI authenticates as API billing, which exposes no 5h/7d windows | `cli_not_authenticated` | 4+ days |

The triggers are upstream and will keep changing. The defect this spec addresses
is the *handling*, which is entirely ours and is identical in both cases.

### Failure chain

Three layers each discard information that the layer below needed:

1. **`server.py::_do_collect`** assigns `self._cached_data = result`
   unconditionally. An error bridge replaces the last good reading. `/quota`
   serves that error despite `_last_collect_ok` being `False`; `/health` knows
   the server is `degraded` and nothing consumes `/health`.
2. **`render.py::_maybe_fetch_quota`** validates only that the response parsed as
   JSON, then overwrites the last-known-good disk cache with the error bridge.
   `compute_quota_vars` maps `status != "ok"` to `X`, carrying no age.
3. **`cli_usage.py`** cannot distinguish "the CLI never started" from "the CLI
   booted into a screen I do not recognise" — both are `cli_boot_timeout` with
   six false booleans. The captured screen is never persisted, so a past
   incident cannot be diagnosed at all. Identical failures retry forever at full
   rate with no escalation.

Measured cost of (3): 2385 failed collections, each booting a 199 MB Node
process for up to 45 s — roughly 18 hours of pointless process startup.

### The invariant being violated

> "I don't know" is rendered as "the answer is X", and the duration of not
> knowing is invisible.

Six-minute-old correct data was destroyed on the *first* failure of each outage
and never came back. A 5-minute gap and a 4-day gap look identical on screen.

## Design

### Bridge status contract

`status` gains a third meaning. This is the central change; everything else
follows from it.

| `status` | Meaning | Numbers present | Renders as |
|---|---|---|---|
| `ok` | Fresh reading | yes | `3.8h: ▃ 61%` |
| `stale` | Real numbers, but older than `QUOTA_FRESH_MAX` | yes | `3.8h: ▃ 61%⋯` |
| `error` | No reading has ever succeeded, or the last good one is older than `QUOTA_GOOD_MAX` | no | `X 4d` |

A `stale` bridge carries the last good numbers plus `age_seconds` and the
`error` code explaining why it stopped refreshing. An `error` bridge carries
`age_seconds` when a previous good reading is known, so the bar can state *how
long* it has been blind.

`⋯` is the existing staleness glyph used for the render-daemon cache; reusing it
keeps one visual language for "this is real but not current".

### Type changes

```
QuotaBridge (dict, on the wire and on disk)
  status       : "ok" | "stale" | "error"
  five_hour    : {utilization: float|"X", resets_at: iso|None}
  seven_day    : {utilization: float|"X", resets_at: iso|None}
  timestamp    : int                 # when these numbers were read
  error        : str|None            # failure code, present when not ok
  age_seconds  : int|None            # NEW — age of the numbers, or of the last good read

CollectionOutcome (new, server-internal)      LastGood (new, server-internal)
  bridge       : QuotaBridge                    bridge : QuotaBridge
  ok           : bool                           at     : float (epoch)
  code         : str|None
```

```
                 ┌─────────────────┐
                 │  UsageCollector │  cli_usage.py
                 │  .collect()     │──── on failure: FailureRecorder.write(screen)
                 └────────┬────────┘
                          │ QuotaBridge (ok | error)
                          ▼
                 ┌─────────────────┐
                 │  QuotaServer    │  server.py
                 │  _last_good ────┼──► retained across failures
                 │  _backoff       │     interval × 2^n, capped
                 └────────┬────────┘
                          │ GET /quota → ok | stale | error (+age_seconds)
                          ▼
                 ┌─────────────────┐
                 │  render daemon  │  render.py
                 │  _maybe_fetch   │──► writes disk cache ONLY when status == ok
                 │  compute_quota  │──► derives status/age from cache mtime + error file
                 └────────┬────────┘
                          │ AGENT_QUOTA_* (incl. AGENT_QUOTA_AGE)
                          ▼
                 ┌─────────────────┐
                 │ tmux-agent-status│ thin reader — renders age, never a bare X
                 └─────────────────┘
```

### Behaviour changes

1. **Retain last-known-good (server).** `_do_collect` replaces `_cached_data`
   only on success. On failure it records the code and serves the retained
   bridge re-stamped as `stale`/`error` with `age_seconds`.
2. **Never overwrite good with bad (daemon).** `_maybe_fetch_quota` writes the
   disk cache only for `status == "ok"`. A non-ok response is written to a
   sibling `claude-quota-error.json`, so the good cache keeps its mtime and the
   age stays computable.
3. **Render age, never a bare `X`.** `compute_quota_vars` emits
   `AGENT_QUOTA_AGE`; `tmux-agent-status` appends `⋯` for `stale` and renders
   `X <age>` for `error`.
4. **Classify unknown screens.** A non-empty screen matching no known marker is
   `cli_unknown_screen`, not `cli_boot_timeout`.
5. **Persist failure screens.** On any screen-derived failure, write the
   captured screen to `~/.cache/tmux-status/usage-failure.txt` with timestamp
   and code, redacting token-shaped runs. One file, overwritten — enough to
   diagnose the current incident without unbounded growth.
6. **Back off and escalate.** Consecutive failures multiply the poll interval
   (×2, capped at `QUOTA_BACKOFF_MAX`, default 1 h). The Nth consecutive failure
   (default 3) logs once at ERROR with the code and the age of the last good
   reading. Success resets both.

### Settings

| Key | Default | Meaning |
|---|---|---|
| `QUOTA_FRESH_MAX` | 900 s | Beyond this the reading renders as `stale` |
| `QUOTA_GOOD_MAX` | 86400 s | Beyond this the reading is dropped; render `X <age>` |
| `QUOTA_BACKOFF_MAX` | 3600 s | Ceiling on the backed-off poll interval |
| `QUOTA_ESCALATE_AFTER` | 3 | Consecutive failures before the ERROR log |

## Non-goals

- **Reading `~/.claude.json` → `cachedUsageUtilization` as a primary source.**
  Investigated and rejected: that cache froze at 2026-09-16 14:58:22, one second
  before the collector's last success, because the collector's own headless CLI
  is what refreshes it. It is a mirror of this pipeline, not an independent
  source, so it fails in lockstep. Recorded here so it is not re-proposed.
- **Auto-answering CLI prompts.** Trust and login decisions stay the user's.
- **Fixing credential state.** Out of scope for this repo by design; the bar's
  job is to report the outage honestly and name the cause.
