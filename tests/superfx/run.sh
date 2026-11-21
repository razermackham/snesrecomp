#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
GCC=${CC:-gcc}
OUT="$ROOT/build/enhancement_opt_in_test"
mkdir -p "$ROOT/build"
# shellcheck disable=SC2086
$GCC -std=c11 -Wall -Wextra -O1 \
  -I"$ROOT/runner/src" -I"$ROOT/runner/src/snes" \
  "$ROOT/tests/superfx/enhancement_opt_in_test.c" \
  "$ROOT/runner/src/snes/superfx.c" \
  -o "$OUT"
"$OUT"
echo "Super FX enhancement tests passed"
