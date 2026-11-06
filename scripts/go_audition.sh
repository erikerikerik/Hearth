#!/usr/bin/env bash
# Plays a set of candidate voices one after another. Needs the speakers on. First run downloads one ~1 GB model.
set -euo pipefail
cd "$(dirname "$0")/.."
.venv-ai/bin/python scripts/voice_audition.py --play
