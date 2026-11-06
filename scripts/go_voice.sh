#!/usr/bin/env bash
# One command for step 1 of the voice loop: install voice pieces, download models, run the smoke test.
set -euo pipefail
cd "$(dirname "$0")/.."
chmod +x scripts/*.sh
bash scripts/install_voice.sh
echo "== running the speech smoke test (first run downloads models if needed)"
HF_HUB_OFFLINE=0 .venv-ai/bin/python scripts/voice_smoke.py
