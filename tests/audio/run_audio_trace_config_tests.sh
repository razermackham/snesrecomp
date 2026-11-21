#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
GCC=${CC:-gcc}
CMAKE=${CMAKE:-cmake}
OUT_DIR=${OUT_DIR:-"$ROOT/build/audio-trace-config-tests"}
mkdir -p "$OUT_DIR"

RUNNER_SRC="$ROOT/runner/src"
CONFIG_TEST_C="$ROOT/tests/audio/audio_trace_history_config_test.c"
CMAKE_SRC="$ROOT/tests/audio/cmake_audio_trace_history"

run_direct() {
  name=$1; expected=$2; shift 2
  out="$OUT_DIR/audio_trace_history_config_${name}"
  rm -f "$out"
  # shellcheck disable=SC2086
  $GCC -std=c11 -Wall -Wextra -Werror -DEXPECT_AUDIO_TRACE_HISTORY=$expected -I "$RUNNER_SRC" "$@" "$CONFIG_TEST_C" -o "$out"
  "$out"
}

run_cmake() {
  name=$1; expected=$2; shift 2
  build="$OUT_DIR/cmake_${name}"
  mkdir -p "$build"
  "$CMAKE" -S "$CMAKE_SRC" -B "$build" -G Ninja -DEXPECT_AUDIO_TRACE_HISTORY=$expected -DSNESRECOMP_ROOT="$ROOT" "$@"
}

run_cmake_invalid() {
  build="$OUT_DIR/cmake_invalid"
  mkdir -p "$build"
  out="$OUT_DIR/cmake_invalid.stdout.log"
  err="$OUT_DIR/cmake_invalid.stderr.log"
  rm -f "$out" "$err"
  if "$CMAKE" -S "$CMAKE_SRC" -B "$build" -G Ninja -DEXPECT_AUDIO_TRACE_HISTORY=0 -DSNESRECOMP_ROOT="$ROOT" -DSNESRECOMP_AUDIO_TRACE_HISTORY=INVALID >"$out" 2>"$err"; then
    echo "invalid CMake audio trace history unexpectedly configured" >&2
    exit 1
  fi
  if ! grep -q "SNESRECOMP_AUDIO_TRACE_HISTORY" "$out" "$err" 2>/dev/null || ! grep -q "INVALID" "$out" "$err" 2>/dev/null; then
    echo "invalid CMake audio trace history failed for an unexpected reason" >&2
    exit 1
  fi
}

run_direct default 1
run_direct trace0_default 1 -DSNESRECOMP_TRACE=0
run_direct explicit_counters 0 -DSNESRECOMP_AUDIO_TRACE_HISTORY=0
run_direct explicit_small 1 -DSNESRECOMP_AUDIO_TRACE_HISTORY=1
run_direct explicit_full 2 -DSNESRECOMP_AUDIO_TRACE_HISTORY=2
run_direct explicit_reserved 3 -DSNESRECOMP_AUDIO_TRACE_HISTORY=3
run_direct trace1_forces_full 2 -DSNESRECOMP_TRACE=1 -DSNESRECOMP_AUDIO_TRACE_HISTORY=0
run_direct cosim_trace0_forces_full 2 -DSNES_COSIM=1 -DSNESRECOMP_TRACE=0 -DSNESRECOMP_AUDIO_TRACE_HISTORY=1

run_cmake default 1
run_cmake explicit_counters 0 -DSNESRECOMP_AUDIO_TRACE_HISTORY=COUNTERS
run_cmake explicit_small 1 -DSNESRECOMP_AUDIO_TRACE_HISTORY=SMALL
run_cmake explicit_full 2 -DSNESRECOMP_AUDIO_TRACE_HISTORY=FULL
run_cmake explicit_reserved 3 -DSNESRECOMP_AUDIO_TRACE_HISTORY=RESERVED
run_cmake trace_forces_full 2 -DSNESRECOMP_ENABLE_TRACE=ON -DSNESRECOMP_AUDIO_TRACE_HISTORY=COUNTERS
run_cmake cosim_forces_full 2 -DSNES_COSIM=ON -DSNESRECOMP_AUDIO_TRACE_HISTORY=SMALL
run_cmake_invalid

echo "audio_trace config matrix passed"
