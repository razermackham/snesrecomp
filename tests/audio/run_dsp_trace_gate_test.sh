#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
GCC=${CC:-gcc}
BUILD="$ROOT/build/audio"
mkdir -p "$BUILD"

BASE_ARGS="-std=c11 -Wall -Wextra -Werror -Wno-unused-function -ffunction-sections -fdata-sections \
  -I$ROOT/runner/src -I$ROOT/runner/src/snes \
  $ROOT/tests/audio/dsp_trace_gate_test.c \
  $ROOT/runner/src/snes/dsp.c \
  $ROOT/runner/src/snes/dsp_clock.c \
  $ROOT/runner/src/snes/dsp_shadow.c \
  $ROOT/runner/src/snes/audio_shadow.c \
  $ROOT/runner/src/audio_trace.c \
  -Wl,--gc-sections -lm"

run_variant() {
  name=$1
  shift
  out="$BUILD/dsp_trace_gate_test_${name}"
  rm -f "$out"
  # shellcheck disable=SC2086
  $GCC "$@" $BASE_ARGS -o "$out"
  "$out" 2>"$BUILD/dsp_trace_gate_test_${name}.stderr.log"
}

run_variant trace_undefined
run_variant trace_0 -DSNESRECOMP_TRACE=0
run_variant trace_1 -DSNESRECOMP_TRACE=1
run_variant cosim -DSNES_COSIM=1 -DSNESRECOMP_TRACE=0

echo "DSP trace-gate tests passed"
