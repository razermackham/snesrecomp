#!/bin/sh
# Linux equivalent helper wrapper for cyc_watch real-ROM diff runs.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
PYTHON=${PYTHON:-python3}
exec "$PYTHON" "$ROOT/tools/cyc_watch/_realrom_diff.py" "$@"
