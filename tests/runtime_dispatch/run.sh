#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
GCC=${CC:-gcc}
OUT="$ROOT/build/known_lle_entry_test"
mkdir -p "$ROOT/build"
# shellcheck disable=SC2086
$GCC -std=c11 -Wall -Wextra -ffunction-sections -fdata-sections \
  -I"$ROOT/runner/src" -I"$ROOT/runner/src/snes" \
  "$ROOT/tests/runtime_dispatch/known_lle_entry_test.c" \
  "$ROOT/runner/src/cpu_state.c" \
  "$ROOT/runner/src/snes/cart.c" \
  "$ROOT/runner/src/snes/cx4.c" \
  "$ROOT/runner/src/snes/dsp1.c" \
  "$ROOT/runner/src/snes/dsp1_hle.c" \
  "$ROOT/runner/src/snes/sa1.c" \
  "$ROOT/runner/src/sha256.c" \
  "$ROOT/runner/src/snes/tier2_capture.c" \
  "$ROOT/runner/src/snes/sdd1.c" \
  "$ROOT/runner/src/snes/interp816.c" \
  -Wl,--gc-sections -lm -o "$OUT"
"$OUT"
echo "dispatch contract tests passed"
