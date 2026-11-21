#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
GCC=${CC:-gcc}
OUT="$ROOT/build/launcher_test"
mkdir -p "$ROOT/build"

EXTRA_LIBS=""
case "$(uname -s 2>/dev/null || echo unknown)" in
  MINGW*|MSYS*|CYGWIN*) EXTRA_LIBS="-lcomdlg32" ;;
esac

# shellcheck disable=SC2086
$GCC -std=c11 -Wall -Wextra -Werror -O1 \
  -I"$ROOT/runner/src" \
  "$ROOT/tests/launcher/launcher_test.c" \
  "$ROOT/runner/src/launcher.c" \
  "$ROOT/runner/src/launcher_cache.c" \
  "$ROOT/runner/src/launcher_picker.c" \
  "$ROOT/runner/src/rom_image_verify.c" \
  "$ROOT/runner/src/rom_identity.c" \
  "$ROOT/runner/src/host_paths.c" \
  "$ROOT/runner/src/crc32.c" \
  "$ROOT/runner/src/sha1.c" \
  "$ROOT/runner/src/sha256.c" \
  $EXTRA_LIBS -o "$OUT"

"$OUT"
echo "launcher tests passed"
