#!/usr/bin/env bash
# Makes a portable copy to install on another computer. Excludes secrets, data, venvs and TLS keys.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="${1:-$HOME/Hearth-bundle-$(date +%Y%m%d).tar.gz}"
tar --exclude='.venv' --exclude='.venv-ai' --exclude='runtime' --exclude='*.sqlite3*' --exclude='*.key' \
    --exclude='ca.crt' --exclude='.hearth-profile' --exclude='__pycache__' --exclude='node_modules' \
    -czf "$OUT" -C .. "$(basename "$PWD")"
echo "wrote $OUT"; echo "On the new machine: untar, python3 -m venv .venv && .venv/bin/pip install -r requirements.txt, scripts/install_models.sh, scripts/tls_setup.sh, scripts/run_https.sh"
