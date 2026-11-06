#!/usr/bin/env bash
# One command: install models, start the local model server, run the benchmark, stop the server.
# Safe to re-run. Needs internet only for the first download.
set -euo pipefail
cd "$(dirname "$0")/.."
chmod +x scripts/*.sh
[ -f .hearth-profile ] && [ -d .venv-ai ] || bash scripts/install_models.sh
PROFILE="$(cat .hearth-profile)"
echo "== starting model server ($PROFILE)"
bash scripts/run_llm.sh > /tmp/hearth_llm.log 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true' EXIT
for i in $(seq 1 120); do
  curl -s --noproxy '*' -m 2 http://127.0.0.1:8081/v1/models >/dev/null 2>&1 && break
  kill -0 $SERVER 2>/dev/null || { echo "server exited; last log lines:"; tail -20 /tmp/hearth_llm.log; exit 1; }
  sleep 2
done
echo "== memory pressure while loaded:"; memory_pressure 2>/dev/null | tail -3 || true
echo "== raw probe (what the server actually sends)"
.venv-ai/bin/python bench/probe.py "$(python3 -c "import json;print(json.load(open('config/models.json'))['profiles']['$PROFILE']['mlx'])")" || true
echo "== benchmark (20 invented conversations)"
.venv-ai/bin/python bench/bench_models.py --profile "$PROFILE"
echo; echo "Read the replies in: $(ls -t bench/results-*.md | head -1)"
echo "Copy everything between the lines above back to Claude."
