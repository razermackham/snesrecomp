#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
GCC=${CC:-gcc}
OUT="$ROOT/build/host_mesh_test"
mkdir -p "$ROOT/build"
# shellcheck disable=SC2086
$GCC -std=c11 -Wall -Wextra -Werror -O2 \
  -I"$ROOT/runner/src" \
  "$ROOT/tests/host_mesh/host_mesh_test.c" \
  "$ROOT/runner/src/host_mesh.c" \
  "$ROOT/runner/src/host_mesh_builder.c" \
  -o "$OUT"
"$OUT"
echo "host mesh tests passed"
