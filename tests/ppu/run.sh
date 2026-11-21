#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
GCC=${CC:-gcc}
BUILD_DIR="$ROOT/build"
mkdir -p "$BUILD_DIR"

TESTS="ppu_sprite_limit_test ppu_world_mirror_test ppu_elastic_band_test ppu_view_anchor_test ppu_mode7_hd_test ppu_mode7_reconstruct_test ppu_raster_journal_test ppu_hires_mode_test ppu_obj_priority_test ppu_brightness_test"
FAILED=""

for test in $TESTS; do
  out="$BUILD_DIR/$test"
  case "$test" in
    ppu_mode7_reconstruct_test)
      SRCS="$ROOT/tests/ppu/$test.c $ROOT/runner/src/snes/hd_jobs.c"
      ;;
    *)
      SRCS="$ROOT/tests/ppu/$test.c $ROOT/runner/src/snes/ppu.c $ROOT/runner/src/snes/hd_jobs.c $ROOT/runner/src/snes/ppu_legacy.c"
      ;;
  esac
  rm -f "$out"
  # shellcheck disable=SC2086
  $GCC -std=c11 -Wall -Wextra -O1 -DSNESRECOMP_REVERSE_DEBUG=0 \
    -I"$ROOT/runner/src" -I"$ROOT/runner/src/snes" \
    $SRCS -o "$out"
  "$out" || FAILED="$FAILED $test"
done

if [ -n "$FAILED" ]; then
  echo "PPU tests failed:$FAILED" >&2
  exit 1
fi
echo "PPU tests passed"
