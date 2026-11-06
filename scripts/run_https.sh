#!/usr/bin/env bash
# Starts Hearth over HTTPS, bound to the mini's LAN address only (never 0.0.0.0).
#   HEARTH_PASSWORD_HASH must be set (see scripts/create_password_hash.py).
# Env: HEARTH_LAN_IP (default: en0 address), HEARTH_PORT (default 8443), HEARTH_TLS_DIR (default ~/Hearth-TLS)
set -euo pipefail
cd "$(dirname "$0")/.."
TLS="${HEARTH_TLS_DIR:-$HOME/Hearth-TLS}"
IP="${HEARTH_LAN_IP:-$(ipconfig getifaddr en0 2>/dev/null || true)}"
[ -n "$IP" ] || { echo "No LAN address found. Set HEARTH_LAN_IP." >&2; exit 1; }
[ -n "${HEARTH_PASSWORD_HASH:-}" ] || { echo "Set HEARTH_PASSWORD_HASH first." >&2; exit 1; }
export HEARTH_COOKIE_SECURE=1 HEARTH_DEV_TOOLS=0
exec .venv/bin/python -m uvicorn app.main:create_app --factory \
  --host "$IP" --port "${HEARTH_PORT:-8443}" \
  --ssl-keyfile "$TLS/therapy.local.key" --ssl-certfile "$TLS/therapy.local.crt" \
  --no-server-header
