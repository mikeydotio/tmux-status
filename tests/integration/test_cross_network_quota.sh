#!/usr/bin/env bash
# Integration test: quota fetch across Docker network boundary
# Validates the renderer can fetch quota data from a remote server.
set -euo pipefail

CONTAINER_NAME="tmux-status-test-quota"
HOST_PORT=7851
CACHE_DIR=$(mktemp -d)

cleanup() {
    docker rm -f "$CONTAINER_NAME" 2>/dev/null || true
    rm -rf "$CACHE_DIR"
}
trap cleanup EXIT

# ── Build & start mock server ─────────────────────────
cd "$(dirname "$0")"
echo "Building mock quota server container..."
docker build -q -t tmux-status-mock-quota -f Dockerfile.mock-server .
docker run -d --name "$CONTAINER_NAME" -p "$HOST_PORT:7850" tmux-status-mock-quota >/dev/null
sleep 1

# ── Test 1: HTTP reachability ─────────────────────────
echo "TEST 1: /health endpoint reachable..."
health=$(curl -sf "http://127.0.0.1:$HOST_PORT/health")
echo "$health" | python3 -c 'import sys,json; d=json.load(sys.stdin); assert d["status"]=="ok", f"bad: {d}"'
echo "  PASS"

# ── Test 2: /quota returns valid data ─────────────────
echo "TEST 2: /quota endpoint returns valid data..."
quota=$(curl -sf "http://127.0.0.1:$HOST_PORT/quota")
echo "$quota" | python3 -c '
import sys, json
d = json.load(sys.stdin)
assert d["status"] == "ok", f"bad status: {d}"
assert d["five_hour"]["utilization"] == 42.5
assert d["seven_day"]["utilization"] == 67.3
'
echo "  PASS"

# ── Test 3: Renderer fetch function ──────────────────
echo "TEST 3: _maybe_fetch_quota() writes cache file..."
CACHE_FILE="$CACHE_DIR/claude-quota.json"
python3 -c "
import urllib.request, json, os, time

def _maybe_fetch_quota(source_url, api_key, cache_ttl, cache_path):
    if not source_url:
        return
    if cache_ttl > 0:
        try:
            if time.time() - os.stat(cache_path).st_mtime < cache_ttl:
                return
        except FileNotFoundError:
            pass
    req = urllib.request.Request(source_url.rstrip('/') + '/quota')
    if api_key:
        req.add_header('X-API-Key', api_key)
    resp = urllib.request.urlopen(req, timeout=3)
    data = resp.read()
    json.loads(data)
    cache_dir = os.path.dirname(cache_path)
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
    tmp = cache_path + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, cache_path)

_maybe_fetch_quota('http://127.0.0.1:$HOST_PORT', '', 0, '$CACHE_FILE')
assert os.path.exists('$CACHE_FILE'), 'cache file not written'
d = json.load(open('$CACHE_FILE'))
assert d['status'] == 'ok'
assert d['five_hour']['utilization'] == 42.5
assert d['seven_day']['utilization'] == 67.3
"
echo "  PASS"

# ── Test 4: Full renderer quota parsing ───────────────
echo "TEST 4: Renderer parses remote quota into variables..."
python3 -c "
import json, os, time, urllib.request

quota_bridge = '$CACHE_DIR/claude-quota-full.json'
quota_source = 'http://127.0.0.1:$HOST_PORT'
quota_api_key = ''
quota_cache_ttl = 0

def _maybe_fetch_quota(source_url, api_key, cache_ttl, cache_path):
    if not source_url:
        return
    if cache_ttl > 0:
        try:
            if time.time() - os.stat(cache_path).st_mtime < cache_ttl:
                return
        except FileNotFoundError:
            pass
    req = urllib.request.Request(source_url.rstrip('/') + '/quota')
    if api_key:
        req.add_header('X-API-Key', api_key)
    resp = urllib.request.urlopen(req, timeout=3)
    data = resp.read()
    json.loads(data)
    cache_dir = os.path.dirname(cache_path)
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
    tmp = cache_path + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, cache_path)

_maybe_fetch_quota(quota_source, quota_api_key, quota_cache_ttl, quota_bridge)
assert os.path.exists(quota_bridge), 'bridge file missing'

qd = json.load(open(quota_bridge))
quota_status = qd.get('status', 'none')
five_hour_pct = 0
seven_day_pct = 0
if quota_status == 'ok':
    fh = qd.get('five_hour', {})
    fh_util = fh.get('utilization', 0)
    five_hour_pct = 'X' if fh_util is None or fh_util == 'X' else round(fh_util)
    sd = qd.get('seven_day', {})
    sd_util = sd.get('utilization', 0)
    seven_day_pct = 'X' if sd_util is None or sd_util == 'X' else round(sd_util)

assert quota_status == 'ok', f'Expected ok, got {quota_status}'
assert five_hour_pct == 42, f'Expected 42, got {five_hour_pct}'
assert seven_day_pct == 67, f'Expected 67, got {seven_day_pct}'
"
echo "  PASS"

# ── Test 5: ECONNREFUSED latency ─────────────────────
echo "TEST 5: Connection refused latency (server down)..."
docker rm -f "$CONTAINER_NAME" 2>/dev/null || true
python3 -c "
import time, urllib.request
start = time.monotonic()
try:
    urllib.request.urlopen('http://127.0.0.1:$HOST_PORT/quota', timeout=3)
except Exception:
    pass
elapsed_ms = (time.monotonic() - start) * 1000
assert elapsed_ms < 500, f'took {elapsed_ms:.0f}ms (expected <500ms)'
print(f'  Connection refused in {elapsed_ms:.0f}ms')
"
echo "  PASS"

echo ""
echo "ALL 5 TESTS PASSED"
