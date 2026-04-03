# Research: Python Packaging & Deployment

## Context
The quota server lives in `server/` within the tmux-status repo but must be installable independently. One required dep: `curl_cffi`. One optional dep: `bottle` (the HTTP framework).

## Python Packaging

### Recommended: `pyproject.toml` with console_scripts (Confidence: High)

`pyproject.toml` is the current standard (PEP 621). `setup.py` is legacy. `setup.cfg` is deprecated in favor of `pyproject.toml`.

```toml
[project]
name = "tmux-status-server"
version = "0.1.0"
description = "Quota data server for tmux-status"
requires-python = ">=3.10"
dependencies = [
    "bottle>=0.12",
    "curl_cffi>=0.5",
]

[project.scripts]
tmux-status-server = "tmux_status_server:main"

[build-system]
requires = ["setuptools>=64"]
build-backend = "setuptools.backends._legacy:_Backend"
```

**Installation**:
- Local: `pip install ./server/` or `pip install -e ./server/`
- Remote (if published): `pip install tmux-status-server`
- No need for PyPI initially — local install from the repo is sufficient

### Package structure

```
server/
  pyproject.toml
  tmux_status_server/
    __init__.py      # package init, version
    __main__.py      # python -m tmux_status_server support
    server.py        # HTTP server (Bottle app, routes, auth middleware)
    scraper.py       # Quota fetching (extracted from tmux-status-quota-fetch)
    config.py        # Configuration loading (CLI, env, file)
```

This is the simplest structure that supports `pip install`, `python -m`, and the console_scripts entry point.

## Configuration Model

### Recommended: CLI flags > env vars > config file > defaults (Confidence: High)

Standard precedence for Python CLI tools:

| Setting | CLI Flag | Env Var | Config Key | Default |
|---------|----------|---------|------------|---------|
| Port | `--port` | `TMUX_STATUS_PORT` | `port` | `7850` |
| Host/bind | `--host` | `TMUX_STATUS_HOST` | `host` | `0.0.0.0` |
| API key | `--api-key` | `TMUX_STATUS_API_KEY` | `api_key` | None (open) |
| Scrape interval | `--interval` | `TMUX_STATUS_INTERVAL` | `interval` | `300` |
| Session key file | `--key-file` | - | `key_file` | `~/.config/tmux-status/claude-usage-key.json` |
| Config file | `--config` | `TMUX_STATUS_CONFIG` | - | None |

### CLI parser: argparse (Confidence: High)
- stdlib, no deps
- `click` and `typer` add dependencies for no real benefit with <10 flags
- argparse is perfectly fine for a server with a handful of options

### Config file format
- TOML would be ideal (stdlib in Python 3.11+, matches pyproject.toml)
- For Python 3.10 compat: use INI-style (like the existing `settings.conf`) or just env vars
- Recommendation: support env vars and CLI flags only. Skip config file — the server has few settings, and Docker/systemd both handle env vars natively.

## Deployment Artifacts

### Dockerfile (Confidence: High)

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY server/ .
RUN pip install --no-cache-dir .
EXPOSE 7850
CMD ["tmux-status-server"]
```

- Use `python:3.12-slim` (not alpine — `curl_cffi` has C extensions that need glibc)
- Multi-stage build is unnecessary — the image is already small
- No need for a non-root user for a LAN-only service, but good practice to add one

### systemd unit (Confidence: High)

```ini
[Unit]
Description=tmux-status quota server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/tmux-status-server
Restart=on-failure
RestartSec=10
Environment=TMUX_STATUS_PORT=7850

[Install]
WantedBy=multi-user.target
```

- `Type=simple` — the server runs in the foreground, systemd manages lifecycle
- Log to stdout — systemd captures via journal automatically
- No PID file needed (systemd tracks the process directly)

### docker-compose.yml (Confidence: Medium)
Include a simple one for convenience:
```yaml
services:
  quota-server:
    build: ./server
    ports:
      - "7850:7850"
    volumes:
      - ./claude-usage-key.json:/config/claude-usage-key.json:ro
    environment:
      - TMUX_STATUS_KEY_FILE=/config/claude-usage-key.json
```

## Daemon Lifecycle

### Signal handling (Confidence: High)
Reuse the same pattern from `tmux-status-quota-poll`:
- `SIGTERM` / `SIGINT` → graceful shutdown (stop accepting requests, finish in-flight, exit)
- `SIGUSR1` → trigger immediate quota fetch (useful for operators)
- Bottle's built-in server handles `KeyboardInterrupt` cleanly

### PID files (Confidence: High)
**Skip PID files.** They're a legacy pattern for SysV init. Both systemd and Docker track processes without them. If someone runs the server manually, they can use `pgrep` or just `kill %1`.

### Logging (Confidence: High)
- Log to stdout/stderr only — let the deployment layer (systemd journal, Docker logs) handle persistence
- Use Python `logging` module with structured messages
- Log level configurable via `--log-level` or `TMUX_STATUS_LOG_LEVEL` (default: `info`)

## Key Recommendations

1. **`pyproject.toml` + `pip install ./server/`** — modern, standard, works everywhere
2. **argparse for CLI** — zero deps, sufficient for <10 flags
3. **Env vars + CLI flags only** — skip config file complexity
4. **Log to stdout** — deployment layer handles the rest
5. **No PID file** — systemd/Docker don't need them
6. **Default port 7850** — uncommon enough to avoid conflicts, easy to remember
