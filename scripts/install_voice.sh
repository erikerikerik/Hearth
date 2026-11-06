#!/usr/bin/env bash
# Adds the text-to-speech language pieces Kokoro needs. Run after install_models.sh. Needs internet once.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -d .venv-ai ] || { echo "Run scripts/install_models.sh first." >&2; exit 1; }
if [ -x .venv-ai/bin/uv ] || command -v uv >/dev/null 2>&1; then
  UVP="$(command -v uv || true)"; PIPI() { "${UVP:-uv}" pip install --python .venv-ai/bin/python "$@"; }
else
  PIPI() { .venv-ai/bin/pip install --quiet "$@"; }
fi
PIPI "misaki[en]" num2words soundfile scipy
# English language data used by the speech front-end (downloaded now so nothing is fetched at run time)
.venv-ai/bin/python - <<'PY'
import importlib, subprocess, sys
try:
    import spacy
    try:
        spacy.load("en_core_web_sm")
    except Exception:
        subprocess.check_call([sys.executable, "-m", "spacy", "download", "en_core_web_sm"])
except ImportError:
    pass
print("voice dependencies ready")
PY
