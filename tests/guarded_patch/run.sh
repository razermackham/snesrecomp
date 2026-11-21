#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
GCC=${CC:-gcc}
OUT="$ROOT/build/guarded_patch_test"
mkdir -p "$ROOT/build"
# shellcheck disable=SC2086
$GCC -std=c11 -Wall -Wextra -Werror \
  -I"$ROOT/runner/src" \
  "$ROOT/tests/guarded_patch/guarded_patch_test.c" \
  "$ROOT/runner/src/guarded_patch.c" \
  -o "$OUT"
"$OUT"
echo "guarded patch tests passed"
