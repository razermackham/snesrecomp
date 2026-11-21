#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
GCC=${CC:-gcc}
OUT="$ROOT/build/apu_port_guest_time_test"
mkdir -p "$ROOT/build"
# shellcheck disable=SC2086
$GCC -std=c11 -Wall -Wextra -Werror \
  -Wno-error=unknown-pragmas -Wno-error=comment \
  -ffunction-sections -fdata-sections \
  -I"$ROOT/runner/src" -I"$ROOT/runner/src/snes" \
  "$ROOT/tests/runtime_dispatch/apu_port_guest_time_test.c" \
  "$ROOT/runner/src/snes/apu.c" \
  "$ROOT/runner/src/snes/spc.c" \
  "$ROOT/runner/src/snes/dsp.c" \
  "$ROOT/runner/src/snes/dsp_clock.c" \
  -Wl,--gc-sections -o "$OUT"
"$OUT"
echo "APU guest-time tests passed"
