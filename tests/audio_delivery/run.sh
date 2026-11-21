#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
GCC=${CC:-gcc}
OUT_DIR="$ROOT/build-tests/audio-delivery"
mkdir -p "$OUT_DIR"
EXE="$OUT_DIR/audio_delivery_test"
cd "$ROOT"
# shellcheck disable=SC2086
$GCC -std=c11 -O2 -flto -fwhole-program -ffunction-sections -fdata-sections \
  -DSNESRECOMP_TRACE=0 -DSNESRECOMP_SDL3=1 -DSDL_MAIN_HANDLED \
  -Irunner/src/desktop -Irunner/src tests/audio_delivery_test.c \
  runner/src/snes/dsp.c runner/src/snes/dsp_clock.c runner/src/audio_trace.c \
  -Wl,--gc-sections -lm -o "$EXE"
"$EXE"
echo "audio delivery tests passed"
