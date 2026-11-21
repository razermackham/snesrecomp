#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
GCC=${CC:-gcc}
OUT_DIR=${OUT_DIR:-"$ROOT/build/audio-trace-tests"}
mkdir -p "$OUT_DIR"

RUNNER_SRC="$ROOT/runner/src"
AUDIO_TRACE_C="$RUNNER_SRC/audio_trace.c"
HISTORY_TEST_C="$ROOT/tests/audio/audio_trace_history_test.c"
CLOCK_TEST_C="$ROOT/tests/audio/audio_trace_clock_gate_test.c"

assert_stats_stderr() {
  path=$1
  grep -q "# ms produced consumed dropped" "$path" || { echo "stderr stats header missing from $path" >&2; exit 1; }
  grep -q '^1000 ' "$path" || { echo "stderr stats cadence row 1000 missing from $path" >&2; exit 1; }
  grep -q '^2000 ' "$path" || { echo "stderr stats cadence row 2000 missing from $path" >&2; exit 1; }
}

for mode in 0 1 2 3; do
  history_exe="$OUT_DIR/audio_trace_history_test_$mode"
  # shellcheck disable=SC2086
  $GCC -std=c11 -Wall -Wextra -Werror -O1 -D_POSIX_C_SOURCE=200809L \
    -DSNESRECOMP_AUDIO_TRACE_HISTORY=$mode -I "$RUNNER_SRC" \
    "$HISTORY_TEST_C" "$AUDIO_TRACE_C" -o "$history_exe"
  (cd "$OUT_DIR" && "$history_exe")

  clock_exe="$OUT_DIR/audio_trace_clock_gate_test_$mode"
  # shellcheck disable=SC2086
  $GCC -std=c11 -Wall -Wextra -Werror -O1 -D_POSIX_C_SOURCE=200809L \
    -DSNESRECOMP_AUDIO_TRACE_HISTORY=$mode \
    -DSNESRECOMP_AUDIO_TRACE_TEST_WALL_MS=1 \
    -DSNESRECOMP_AUDIO_TRACE_TEST_FOPEN=1 \
    -DSNESRECOMP_AUDIO_TRACE_TEST_GETENV=1 \
    -I "$RUNNER_SRC" "$CLOCK_TEST_C" "$AUDIO_TRACE_C" -o "$clock_exe"

  stats_path="$OUT_DIR/audio_trace_clock_gate_stats_$mode.log"
  fail_path="$OUT_DIR/audio_trace_clock_gate_fail_$mode.log"
  stderr_path="$OUT_DIR/audio_trace_clock_gate_stderr_$mode.log"
  rm -f "$stats_path" "$fail_path" "$stderr_path"

  env -u SNESRECOMP_AUDIO_STATS -u SNESRECOMP_AUDIO_TRACE_TEST_FOPEN_FAIL "$clock_exe" off
  env -u SNESRECOMP_AUDIO_STATS -u SNESRECOMP_AUDIO_TRACE_TEST_FOPEN_FAIL "$clock_exe" snap
  env -u SNESRECOMP_AUDIO_TRACE_TEST_FOPEN_FAIL "$clock_exe" off-empty
  env -u SNESRECOMP_AUDIO_TRACE_TEST_FOPEN_FAIL "$clock_exe" snap-empty
  env -u SNESRECOMP_AUDIO_TRACE_TEST_FOPEN_FAIL "$clock_exe" off-zero
  env -u SNESRECOMP_AUDIO_TRACE_TEST_FOPEN_FAIL "$clock_exe" snap-zero
  env -u SNESRECOMP_AUDIO_TRACE_TEST_FOPEN_FAIL SNESRECOMP_AUDIO_STATS=1 "$clock_exe" stderr 2>"$stderr_path"
  assert_stats_stderr "$stderr_path"
  env -u SNESRECOMP_AUDIO_TRACE_TEST_FOPEN_FAIL SNESRECOMP_AUDIO_STATS="$stats_path" "$clock_exe" path
  env SNESRECOMP_AUDIO_STATS="$fail_path" SNESRECOMP_AUDIO_TRACE_TEST_FOPEN_FAIL=1 "$clock_exe" open-fail
done

echo "audio_trace history/clock matrix passed"
