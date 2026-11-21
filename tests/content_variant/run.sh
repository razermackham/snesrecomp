#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
GCC=${CC:-gcc}
OUT_DIR="$ROOT/build"
OUT="$OUT_DIR/content_variant_test"
mkdir -p "$OUT_DIR"
# shellcheck disable=SC2086
$GCC -std=c11 -Wall -Wextra -Werror \
  -I"$ROOT/runner/src" -I"$ROOT/runner/src/snes" -I"$ROOT/third_party" \
  -DSNESRECOMP_ENABLE_MODS=0 \
  "$ROOT/tests/content_variant/content_variant_test.c" \
  "$ROOT/runner/src/content_variant.c" \
  "$ROOT/runner/src/variant_selector.c" \
  "$ROOT/runner/src/program_module.c" \
  "$ROOT/runner/src/rom_patch.c" \
  "$ROOT/runner/src/crc32.c" \
  "$ROOT/runner/src/sha256.c" \
  "$ROOT/runner/src/snes_overlay_draw.c" \
  -o "$OUT"
(cd "$OUT_DIR" && "$OUT")
echo "content variant tests passed"
