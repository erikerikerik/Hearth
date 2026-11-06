#!/bin/bash
# Double-click this file on the M3 MacBook to run the complete Hearth test bed locally.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
exec /bin/bash "$ROOT/scripts/launch_testbed.sh" "$@"
