#!/usr/bin/env bash
# Local model server, loopback only. Never change --host to anything but 127.0.0.1.
set -euo pipefail
cd "$(dirname "$0")/.."
PROFILE="${HEARTH_PROFILE:-$(cat .hearth-profile 2>/dev/null || echo fast)}"
MODEL=$(.venv-ai/bin/python -c "import json;print(json.load(open('config/models.json'))['profiles']['$PROFILE']['mlx'])")
echo "serving $MODEL on 127.0.0.1:8081 (offline: weights already downloaded)"
HF_HUB_OFFLINE=1 exec .venv-ai/bin/python -m mlx_lm.server --model "$MODEL" --host 127.0.0.1 --port 8081
