#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
GCC=${CC:-gcc}
OUT="$ROOT/build/program_module_test"
mkdir -p "$ROOT/build"
# shellcheck disable=SC2086
$GCC -std=c11 -Wall -Wextra -Werror \
  -I"$ROOT/runner/src" -I"$ROOT/runner/src/snes" \
  "$ROOT/tests/program_module/program_module_test.c" \
  "$ROOT/runner/src/program_module.c" \
  "$ROOT/runner/src/sha256.c" \
  -o "$OUT"
"$OUT"
echo "program module tests passed"
