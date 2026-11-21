#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
GCC=${CC:-gcc}
BUILD_DIR="$ROOT/build"
HEAD_DIR="$BUILD_DIR/ppu_composition_head"
HEAD_SOURCE="$HEAD_DIR/ppu_head.c"
HEAD_OUT="$BUILD_DIR/ppu_composition_head_test"
CANDIDATE_OUT="$BUILD_DIR/ppu_composition_candidate_test"
BENCH=0
BENCH_LOOPS=100

while [ $# -gt 0 ]; do
  case "$1" in
    --bench) BENCH=1; shift ;;
    --bench-loops) BENCH_LOOPS=$2; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

mkdir -p "$BUILD_DIR" "$HEAD_DIR"
git -C "$ROOT" show HEAD:runner/src/snes/ppu.c > "$HEAD_SOURCE"

build_test() {
  out=$1
  ppu_src=${2:-}
  rm -f "$out"
  if [ -n "$ppu_src" ]; then
    # shellcheck disable=SC2086
    $GCC -std=c11 -Wall -Wextra -O2 -DSNESRECOMP_REVERSE_DEBUG=0 \
      "-DPPU_COMPOSITION_PPU_INCLUDE=\"$ppu_src\"" \
      -I"$ROOT/runner/src" -I"$ROOT/runner/src/snes" \
      "$ROOT/tests/ppu/ppu_composition_regression_test.c" \
      "$ROOT/runner/src/snes/ppu_legacy.c" -o "$out"
  else
    # shellcheck disable=SC2086
    $GCC -std=c11 -Wall -Wextra -O2 -DSNESRECOMP_REVERSE_DEBUG=0 \
      -I"$ROOT/runner/src" -I"$ROOT/runner/src/snes" \
      "$ROOT/tests/ppu/ppu_composition_regression_test.c" \
      "$ROOT/runner/src/snes/ppu_legacy.c" -o "$out"
  fi
}

build_test "$HEAD_OUT" "$HEAD_SOURCE"
build_test "$CANDIDATE_OUT"

head_digest=$("$HEAD_OUT" --digest | tail -n 1)
candidate_digest=$("$CANDIDATE_OUT" --digest | tail -n 1)
if [ "$head_digest" != "$candidate_digest" ]; then
  echo "digest mismatch: HEAD=$head_digest candidate=$candidate_digest" >&2
  exit 1
fi

"$CANDIDATE_OUT"

if [ "$BENCH" -eq 1 ]; then
  i=1
  while [ "$i" -le 5 ]; do
    echo "bench_pair=$i"
    "$HEAD_OUT" --render-bench "$BENCH_LOOPS"
    "$CANDIDATE_OUT" --render-bench "$BENCH_LOOPS"
    i=$((i + 1))
  done
fi

echo "composition regression tests passed"
