#!/bin/bash
# Hearth local test-bed launcher for macOS.
#
# Everything stays on this Mac:
#   Brave -> 127.0.0.1:4173 -> local Whisper/Kokoro + 127.0.0.1:8081 Gemma
#
# The launcher never downloads models, writes the password to disk, or exposes a LAN port.
# Press Control-C in its dedicated Terminal window to stop every process it started.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$ROOT/.venv-ai/bin/python"
BRAVE="/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
DATA="$ROOT/runtime/testbed"
LOGS="$ROOT/runtime/testbed-logs"
LLM_URL="http://127.0.0.1:8081/v1/models"
APP_URL="http://127.0.0.1:4173"
LLM_PID=""
APP_PID=""

say() { printf '%s\n' "$*"; }
fail() { printf '\nHearth could not start: %s\n' "$*" >&2; exit 1; }
http_ok() { /usr/bin/curl --silent --fail --max-time 2 --noproxy '*' "$1" >/dev/null 2>&1; }

require_local_install() {
  [ "$(uname -s)" = "Darwin" ] || fail "this launcher is for macOS"
  [ "$(uname -m)" = "arm64" ] || fail "Hearth's MLX test bed requires an Apple-silicon Mac"
  [ -x "$PYTHON" ] || fail "missing .venv-ai. Run: bash scripts/install_models.sh"
  [ -x "$BRAVE" ] || fail "Brave is not installed in /Applications"
  [ -x "$ROOT/scripts/run_llm.sh" ] || fail "scripts/run_llm.sh is missing or not executable"
  [ -f "$ROOT/run_dev.py" ] || fail "run_dev.py is missing"
}

cleanup() {
  trap - EXIT INT TERM HUP
  say ""
  say "Stopping the Hearth processes started by this launcher…"
  [ -n "$APP_PID" ] && /bin/kill "$APP_PID" 2>/dev/null || true
  [ -n "$LLM_PID" ] && /bin/kill "$LLM_PID" 2>/dev/null || true
  [ -n "$APP_PID" ] && wait "$APP_PID" 2>/dev/null || true
  [ -n "$LLM_PID" ] && wait "$LLM_PID" 2>/dev/null || true
  say "Hearth stopped."
}
trap cleanup EXIT INT TERM HUP

require_local_install

if [ "${1:-}" = "--check" ]; then
  "$PYTHON" -c 'import argon2, fastapi, uvicorn, websockets' || fail "the Hearth Python environment is incomplete"
  "$PYTHON" -c 'import mlx, mlx_lm, mlx_audio, mlx_whisper' || fail "the local MLX packages are incomplete"
  say "Hearth test-bed prerequisites are present on this Mac."
  trap - EXIT INT TERM HUP
  exit 0
fi

if http_ok "$APP_URL/healthz"; then
  say "Hearth is already running at $APP_URL. Opening it in Brave."
  /usr/bin/open -a "Brave Browser" "$APP_URL"
  trap - EXIT INT TERM HUP
  exit 0
fi

if /usr/sbin/lsof -nP -iTCP:4173 -sTCP:LISTEN >/dev/null 2>&1; then
  fail "port 4173 is occupied by something other than Hearth"
fi

printf 'Choose the temporary test-bed password: '
IFS= read -r -s HEARTH_PASSWORD
printf '\n'
[ "${#HEARTH_PASSWORD}" -ge 12 ] || fail "use at least 12 characters"

/bin/mkdir -p "$DATA" "$LOGS"
/bin/chmod 700 "$DATA" "$LOGS"

say "Starting the local Gemma server…"
if http_ok "$LLM_URL"; then
  say "A compatible loopback model server is already responding; reusing it."
else
  if /usr/sbin/lsof -nP -iTCP:8081 -sTCP:LISTEN >/dev/null 2>&1; then
    fail "port 8081 is occupied but does not answer the local model endpoint"
  fi
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 /bin/bash "$ROOT/scripts/run_llm.sh" >"$LOGS/llm.log" 2>&1 &
  LLM_PID=$!
  for _ in $(seq 1 180); do
    http_ok "$LLM_URL" && break
    /bin/kill -0 "$LLM_PID" 2>/dev/null || { /usr/bin/tail -40 "$LOGS/llm.log" >&2; fail "the local model server exited"; }
    /bin/sleep 1
  done
  http_ok "$LLM_URL" || { /usr/bin/tail -40 "$LOGS/llm.log" >&2; fail "the local model did not become ready within three minutes"; }
fi

say "Starting Hearth's local UI, memory and speech loop…"
HEARTH_DEV_PASSWORD="$HEARTH_PASSWORD" \
HEARTH_COOKIE_SECURE=0 \
HEARTH_DEV_TOOLS=0 \
HEARTH_LLM_ENABLED=1 \
HEARTH_VOICE_ENABLED=1 \
HEARTH_DATA_DIR="$DATA" \
HEARTH_DB_PATH="$DATA/hearth.sqlite3" \
HF_HUB_OFFLINE=1 \
TRANSFORMERS_OFFLINE=1 \
  "$PYTHON" "$ROOT/run_dev.py" >"$LOGS/hearth.log" 2>&1 &
APP_PID=$!
unset HEARTH_PASSWORD

for _ in $(seq 1 120); do
  http_ok "$APP_URL/healthz" && break
  /bin/kill -0 "$APP_PID" 2>/dev/null || { /usr/bin/tail -60 "$LOGS/hearth.log" >&2; fail "the Hearth server exited"; }
  /bin/sleep 1
done
http_ok "$APP_URL/healthz" || { /usr/bin/tail -60 "$LOGS/hearth.log" >&2; fail "Hearth did not become ready within two minutes"; }

BUILD_ID="$(/usr/bin/curl --silent --noproxy '*' "$APP_URL/healthz" | "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin).get("build_id", "unknown build"))')"
say ""
say "Hearth $BUILD_ID is ready and 100% local on this Mac."
say "Data: $DATA"
say "Logs: $LOGS"
say "Press Control-C here once to stop Hearth and the model server."
/usr/bin/open -a "Brave Browser" "$APP_URL"

wait "$APP_PID"
