#!/bin/sh
# Linux equivalent helper wrapper for cyc_watch sanity checks.
# Mirrors the intent of _sanity.ps1 by running the Python sanity script.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
PYTHON=${PYTHON:-python3}
exec "$PYTHON" "$ROOT/tools/cyc_watch/_sanity.py" "$@"
