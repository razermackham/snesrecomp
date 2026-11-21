#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
GCC=${CC:-gcc}
mkdir -p "$ROOT/build"

OUT="$ROOT/build/diagnostic_gates_test"
# shellcheck disable=SC2086
$GCC -std=c11 -Wall -Wextra -Werror -ffunction-sections -fdata-sections \
  -I"$ROOT/runner/src" -I"$ROOT/runner/src/snes" \
  "$ROOT/tests/runtime_dispatch/diagnostic_gates_test.c" \
  "$ROOT/runner/src/common_cpu_infra.c" \
  -Wl,--gc-sections -o "$OUT"
"$OUT"

WLOG_OUT="$ROOT/build/wlog_addr_lazy_test"
# shellcheck disable=SC2086
$GCC -std=c11 -Wall -Wextra -Werror -ffunction-sections -fdata-sections \
  -I"$ROOT/runner/src" -I"$ROOT/runner/src/snes" \
  "$ROOT/tests/runtime_dispatch/wlog_addr_lazy_test.c" \
  "$ROOT/runner/src/cpu_state.c" \
  -Wl,--wrap=getenv -Wl,--gc-sections -lm -o "$WLOG_OUT"
for mode in unset empty invalid; do
  "$WLOG_OUT" "$mode"
done

APU_DIAG_OUT="$ROOT/build/apu_port_diag_getenv_test"
# shellcheck disable=SC2086
$GCC -std=c11 -Wall -Wextra -Werror -Wno-unused-function -Wno-unused-parameter \
  -ffunction-sections -fdata-sections -DSNESRECOMP_APU_PORT_DIAG_TEST=1 \
  -I"$ROOT/runner/src" -I"$ROOT/runner/src/snes" \
  "$ROOT/tests/runtime_dispatch/apu_port_diag_getenv_test.c" \
  "$ROOT/runner/src/snes/interp_bridge.c" \
  -Wl,--wrap=getenv -Wl,--gc-sections -lm -o "$APU_DIAG_OUT"
for mode in unset-apu empty-apu zero-apu unset-nonport empty-nonport zero-nonport; do
  "$APU_DIAG_OUT" "$mode" 2>"$ROOT/build/apu_port_diag_getenv_${mode}.stderr.log"
done

CART_BUS_OUT="$ROOT/build/cart_cpu_bus_latch_test"
# shellcheck disable=SC2086
$GCC -std=c11 -Wall -Wextra -Werror -Wno-unused-function -Wno-unused-parameter \
  -ffunction-sections -fdata-sections \
  -I"$ROOT/runner/src" -I"$ROOT/runner/src/snes" \
  "$ROOT/tests/runtime_dispatch/cart_cpu_bus_latch_test.c" \
  "$ROOT/runner/src/cpu_state.c" \
  -Wl,--gc-sections -lm -o "$CART_BUS_OUT"
"$CART_BUS_OUT"

echo "diagnostic gate tests passed"
