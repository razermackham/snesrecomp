#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
GCC=${CC:-gcc}
OUT="$ROOT/build/rom_patch_test"
mkdir -p "$ROOT/build"
# shellcheck disable=SC2086
$GCC -std=c11 -Wall -Wextra -Werror \
  -I"$ROOT/runner/src" \
  "$ROOT/tests/rom_patch/rom_patch_test.c" \
  "$ROOT/runner/src/rom_patch.c" \
  "$ROOT/runner/src/crc32.c" \
  -o "$OUT"
"$OUT"
echo "ROM patch tests passed"
