#!/usr/bin/env bash
# test_context_hook.sh — unit test for the Claude statusLine bridge hook
# (scripts/tmux-status-context-hook.js).
#
# Asserts the bridge file now carries the model (so the render daemon can show
# the Claude lines on a fresh/`/clear`'d session before any assistant reply),
# that a context-less payload still records the model, that an identical re-fire
# is deduped (no rewrite, no wasteful poke), and that malformed input exits 0.

set -u

HOOK="$(cd "$(dirname "$0")/../.." && pwd)/scripts/tmux-status-context-hook.js"

if ! command -v node >/dev/null 2>&1; then
    echo "node not installed; skipping context-hook test"
    exit 0
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export HOME="$TMP"

# Stub the poke binary the hook spawns ($HOME/.local/bin/tmux-status-poke) so it
# records invocations instead of signalling a real daemon.
mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/tmux-status-poke" <<'EOF'
#!/usr/bin/env bash
echo x >> "$HOME/poke.log"
EOF
chmod +x "$HOME/.local/bin/tmux-status-poke"

BRIDGE_DIR="$HOME/.cache/tmux-status"
fail() { echo "FAIL: $1"; exit 1; }
run_hook() { node "$HOOK" || fail "hook exited non-zero"; }

# 1) Fresh session: model + context -> bridge carries BOTH (model is the fix).
echo '{"session_id":"hooktest-1","model":{"id":"claude-opus-4-8","display_name":"Opus 4.8"},"context_window":{"used_percentage":12,"remaining_percentage":88}}' | run_hook
B1="$BRIDGE_DIR/claude-ctx-hooktest-1.json"
[ -f "$B1" ] || fail "bridge not written for fresh session"
grep -q '"model":"claude-opus-4-8"' "$B1" || fail "model not in bridge ($(cat "$B1"))"
grep -q '"used_pct":12' "$B1" || fail "used_pct not in bridge ($(cat "$B1"))"

# Poke fired on the (real) write — poll briefly since the spawn is detached.
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
    [ -s "$HOME/poke.log" ] && break; sleep 0.1
done
[ -s "$HOME/poke.log" ] || fail "poke not fired on write"

# 2) Dedupe: an identical re-fire must NOT rewrite the bridge. Prove it with a
#    sentinel key the hook never writes — it survives iff the write was skipped.
python3 - "$B1" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p)); d["sentinel"] = True
json.dump(d, open(p, "w"))
PY
echo '{"session_id":"hooktest-1","model":{"id":"claude-opus-4-8","display_name":"Opus 4.8"},"context_window":{"used_percentage":12,"remaining_percentage":88}}' | run_hook
grep -q 'sentinel' "$B1" || fail "dedupe failed: identical re-fire rewrote the bridge"

# 3) A real change rewrites the bridge (sentinel gone, used_pct updated).
echo '{"session_id":"hooktest-1","model":{"id":"claude-opus-4-8","display_name":"Opus 4.8"},"context_window":{"used_percentage":30,"remaining_percentage":70}}' | run_hook
grep -q 'sentinel' "$B1" && fail "changed payload did not rewrite the bridge"
grep -q '"used_pct":30' "$B1" || fail "used_pct not updated on change"

# 4) Context-less payload (session + model only) still records the model so a
#    not-yet-warmed session is never blank.
echo '{"session_id":"hooktest-2","model":{"id":"claude-sonnet-4-6"}}' | run_hook
B2="$BRIDGE_DIR/claude-ctx-hooktest-2.json"
[ -f "$B2" ] || fail "bridge not written without context_window"
grep -q '"model":"claude-sonnet-4-6"' "$B2" || fail "model missing for ctx-less payload"
grep -q '"used_pct":0' "$B2" || fail "used_pct default missing for ctx-less payload"

# 5) Malformed stdin still exits 0 (silent-failure contract).
echo 'not json' | node "$HOOK" || fail "hook must exit 0 on malformed input"

echo "✓ test_context_hook.sh passed"
