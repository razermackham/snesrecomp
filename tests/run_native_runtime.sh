#!/bin/sh
# Linux/macOS equivalent of tests/run_native_runtime.ps1
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
COMPILER=${COMPILER:-cc}
OUTPUT_DIRECTORY=${OUTPUT_DIRECTORY:-"$ROOT/build/native-runtime"}
BENCH=0

while [ $# -gt 0 ]; do
  case "$1" in
    --compiler)
      COMPILER=$2; shift 2 ;;
    --output-directory)
      OUTPUT_DIRECTORY=$2; shift 2 ;;
    --bench)
      BENCH=1; shift ;;
    -h|--help)
      echo "Usage: $0 [--compiler cc] [--output-directory dir] [--bench]"
      exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2 ;;
  esac
done

mkdir -p "$OUTPUT_DIRECTORY"

COMMON="-std=c11 -O3 -UNDEBUG -DSNESRECOMP_TRACE=0 -ffunction-sections -fdata-sections -I$ROOT/runner/src"
AUDIO_SOURCES="$ROOT/tests/audio/apu_native_test.c $ROOT/runner/src/snes/spc.c $ROOT/runner/src/snes/dsp.c $ROOT/runner/src/snes/dsp_clock.c $ROOT/runner/src/snes/dsp_shadow.c $ROOT/runner/src/snes/audio_shadow.c $ROOT/runner/src/audio_trace.c"

for native in 0 1; do
  out="$OUTPUT_DIRECTORY/apu-native-$native"
  # shellcheck disable=SC2086
  $COMPILER $COMMON -DSNESRECOMP_APU_NATIVE=$native $AUDIO_SOURCES -Wl,--gc-sections -lm -o "$out"
  "$out"
  if [ "$BENCH" -eq 1 ] && [ "$native" -eq 1 ]; then
    "$out" --bench
  fi
done

out="$OUTPUT_DIRECTORY/ppu-native-raster"
# shellcheck disable=SC2086
$COMPILER $COMMON -DSNESRECOMP_REVERSE_DEBUG=0 -I"$ROOT/runner/src/snes" \
  "$ROOT/tests/ppu/ppu_native_raster_test.c" "$ROOT/runner/src/snes/ppu_legacy.c" -o "$out"
"$out"

for slices in 1 8; do
  out="$OUTPUT_DIRECTORY/crc32-$slices"
  # shellcheck disable=SC2086
  $COMPILER $COMMON -DSNESRECOMP_CRC32_SLICES=$slices \
    "$ROOT/tests/crc32_native_test.c" "$ROOT/runner/src/crc32.c" -o "$out"
  "$out"
done

echo "run_native_runtime.sh: all checks passed"
