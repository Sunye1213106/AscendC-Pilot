#!/usr/bin/env bash
# Where the replay driver's dependencies actually are on this machine.
set -u

if [ -n "${REPLAY_CANN_ENV:-}" ] && [ -f "$REPLAY_CANN_ENV" ]; then
  # shellcheck disable=SC1090
  source "$REPLAY_CANN_ENV" >/dev/null 2>&1 || true
fi
CANN_PKG="${CANN_PKG_ROOT:-}"
CANN="${ASCEND_HOME_PATH:-$CANN_PKG}"
OPS=${OPS_ROOT:-/work/ops-transformer}

echo "CANN_PKG_ROOT=$CANN_PKG"
echo "ASCEND_HOME_PATH=$CANN"
echo "OPS=$OPS"
echo

hunt() {
  local label=$1 name=$2; shift 2
  local hit
  hit=$(find "$@" -name "$name" 2>/dev/null | head -3)
  if [ -n "$hit" ]; then
    echo "$label:"; echo "$hit" | sed 's/^/    /'
  else
    echo "$label: MISSING"
  fi
}

hunt "gtest/gtest.h" "gtest.h" "$CANN_PKG" "$CANN" /usr/include /usr/local/include
hunt "nlohmann/json.hpp" "json.hpp" "$CANN_PKG" "$CANN" /usr/include /usr/local/include "$OPS"
hunt "op_tiling_context_builder.h" "op_tiling_context_builder.h" "$CANN_PKG" "$CANN" "$OPS"
hunt "platform_ascendc.h" "platform_ascendc.h" "$CANN_PKG" "$CANN"
hunt "tiling_base.h(op_host)" "tiling_base.h" "$OPS/common/include"

echo
echo "=== build tree ==="
ls -d "$OPS/build" 2>/dev/null || echo "no $OPS/build"
find "$OPS/build" -name 'libophost_transformer_ut.so' 2>/dev/null | head -2
echo
echo "=== key libs ==="
if [ -n "$CANN_PKG" ]; then
  for l in tiling_api runtime ascendalog metadef register opp_registry graph platform unified_dlog; do
    f=$(find "$CANN_PKG" -name "lib${l}.so" -o -name "lib${l}.a" 2>/dev/null | head -1)
    printf '  %-22s %s\n' "$l" "${f:-MISSING}"
  done
fi
