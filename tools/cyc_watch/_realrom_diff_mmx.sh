#!/bin/sh
# Linux equivalent helper wrapper for MMX real-ROM diff runs.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
PYTHON=${PYTHON:-python3}
exec "$PYTHON" "$ROOT/tools/cyc_watch/_realrom_diff_mmx.py" "$@"
