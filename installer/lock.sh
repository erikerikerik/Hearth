#!/bin/bash
# Re-resolve installer/requirements-app.lock from requirements-app.in.
# Runs on any machine with uv (https://docs.astral.sh/uv/); resolves for the app's target:
# Apple silicon, macOS 14+, CPython 3.12. Commit the resulting lock; build.sh installs only from it.
set -euo pipefail
cd "$(dirname "$0")"
MACOSX_DEPLOYMENT_TARGET=14.0 uv pip compile requirements-app.in \
  --python-version 3.12 --python-platform aarch64-apple-darwin \
  --generate-hashes --only-binary :all: --no-header --emit-index-url \
  -o requirements-app.lock
echo "Wrote installer/requirements-app.lock"
