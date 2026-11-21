#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
GCC=${CC:-gcc}
OUT_DIR="$ROOT/build-tests/dma-snapshot"
mkdir -p "$OUT_DIR"
EXE="$OUT_DIR/dma_snapshot_test"
# shellcheck disable=SC2086
$GCC -std=c11 -O2 -flto -fwhole-program -ffunction-sections -fdata-sections \
  -DSNESRECOMP_TRACE=0 -DSNESRECOMP_SDL3=1 -DSDL_MAIN_HANDLED \
  -I"$ROOT/runner/src/desktop" -I"$ROOT/runner/src" \
  "$ROOT/tests/dma_snapshot_test.c" \
  "$ROOT/runner/src/snes/dma.c" \
  -Wl,--gc-sections -lm -o "$EXE"
"$EXE"
echo "DMA snapshot tests passed"
