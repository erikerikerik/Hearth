#!/usr/bin/env bash
# Installs the local AI stack on an Apple-silicon Mac and downloads one model profile.
#   HEARTH_PROFILE=fast|balanced|large  (default: auto-picked from installed RAM, capped by config default)
# Network is needed ONLY here, to download weights from Hugging Face. Runtime is loopback-only.
set -euo pipefail
cd "$(dirname "$0")/.."
[ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ] || { echo "This script is for Apple-silicon Macs. On other machines run a llama.cpp/Ollama server on 127.0.0.1:8081 instead (see docs/MODELS_AND_PORTING.md)." >&2; exit 1; }
RAM_GB=$(( $(sysctl -n hw.memsize) / 1073741824 ))
auto(){ if [ "$RAM_GB" -ge 48 ]; then echo large; elif [ "$RAM_GB" -ge 24 ]; then echo "$1"; else echo fast; fi; }
DEFAULT=$(python3 -c "import json;print(json.load(open('config/models.json'))['default_profile'])")
PROFILE="${HEARTH_PROFILE:-$(auto "$DEFAULT")}"
echo "RAM: ${RAM_GB} GB -> profile: $PROFILE"
# mlx-lm needs Python 3.11+. macOS ships 3.9, which is too old.
find_py(){ for c in python3.13 python3.12 python3.11 /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 /usr/local/bin/python3.12 /usr/local/bin/python3.11; do
  p=$(command -v "$c" 2>/dev/null || true); [ -n "$p" ] && "$p" -c 'import sys;sys.exit(0 if sys.version_info>=(3,11) else 1)' 2>/dev/null && { echo "$p"; return; }; done; }
PY=$(find_py || true)
# discard a venv built earlier with a too-old Python
if [ -d .venv-ai ] && ! .venv-ai/bin/python -c 'import sys;sys.exit(0 if sys.version_info>=(3,11) else 1)' 2>/dev/null; then rm -rf .venv-ai; fi
if [ ! -d .venv-ai ]; then
  if [ -n "$PY" ]; then "$PY" -m venv .venv-ai
  elif command -v uv >/dev/null 2>&1 || [ -x "$HOME/.local/bin/uv" ]; then
    UV=$(command -v uv || echo "$HOME/.local/bin/uv"); "$UV" venv --seed --python 3.12 .venv-ai
  elif command -v brew >/dev/null 2>&1; then
    echo "Installing Python 3.12 with Homebrew..."; brew install python@3.12; PY=$(find_py); "$PY" -m venv .venv-ai
  else
    echo "No Python 3.11+ found, and neither uv nor Homebrew is installed." >&2
    echo "Install uv (official, from astral.sh): run  curl -LsSf https://astral.sh/uv/install.sh | sh  then open a new Terminal and re-run this." >&2
    echo "Or install Python 3.12 from https://www.python.org/downloads/macos/ and re-run." >&2
    exit 1
  fi
fi
.venv-ai/bin/python -m ensurepip --upgrade >/dev/null 2>&1 || true
.venv-ai/bin/python -m pip install --quiet --upgrade pip
# Hearth's own server packages (FastAPI, uvicorn, ...) — the test bed runs the app from this same environment
.venv-ai/bin/python -m pip install --quiet -r requirements.txt
read -r LM WH AU < <(python3 -c "import json;p=json.load(open('config/models.json'))['packages'];print(p['mlx-lm'],p['mlx-whisper'],p['mlx-audio'])")
.venv-ai/bin/pip install --quiet "mlx-lm==$LM" "mlx-whisper==$WH" "mlx-audio==$AU" huggingface_hub
MODEL=$(python3 -c "import json,sys;print(json.load(open('config/models.json'))['profiles']['$PROFILE']['mlx'])")
STT=$(python3 -c "import json;print(json.load(open('config/models.json'))['stt']['mlx'])")
TTS=$(python3 -c "import json;print(json.load(open('config/models.json'))['tts']['mlx'])")
for m in "$MODEL" "$STT" "$TTS"; do echo "downloading $m"; .venv-ai/bin/python -c "from huggingface_hub import snapshot_download as d;print(d('$m'))"; done
echo "$PROFILE" > .hearth-profile
echo "Done. Start the model server with: scripts/run_llm.sh   Then benchmark: .venv-ai/bin/python bench/bench_models.py"
