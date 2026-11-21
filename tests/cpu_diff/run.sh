#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
GCC=${CC:-gcc}
PYTHON=${PYTHON:-python3}

echo "=== regen single-opcode functions ==="
"$PYTHON" "$ROOT/tests/cpu_diff/gen_ops.py"

mkdir -p "$ROOT/build"
echo "=== build ==="
# shellcheck disable=SC2086
$GCC -std=c11 -O1 -w -I "$ROOT/runner/src" -I "$ROOT/runner/src/snes" \
  "$ROOT/tests/cpu_diff/cpu_diff.c" "$ROOT/tests/cpu_diff/gen_ops.c" \
  "$ROOT/runner/src/snes/interp816.c" -o "$ROOT/build/cpu_diff"

echo "=== run ==="
"$ROOT/build/cpu_diff"
