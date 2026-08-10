#!/usr/bin/env bash
# Where the replay driver's dependencies actually are on this machine.
# Run: wsl -d Ubuntu-22.04 -e bash <this>
set -u

source /usr/local/Ascend/cann/set_env.sh >/dev/null 2>&1 || true
CANN="${ASCEND_HOME_PATH:-/usr/local/Ascend/cann}"
OPS=/work/ops-transformer

echo "CANN=$CANN"
echo "OPS=$OPS"
echo

hunt() {  # hunt <label> <name> <dir>...
  local label=$1 name=$2; shift 2
  local hit
  hit=$(find "$@" -name "$name" 2>/dev/null | head -3)
  if [ -n "$hit" ]; then
    echo "$label:"; echo "$hit" | sed 's/^/    /'
  else
    echo "$label: MISSING"
  fi
}

hunt "gtest/gtest.h" "gtest.h" "$CANN" /usr/include /usr/local/include
hunt "nlohmann/json.hpp" "json.hpp" "$CANN" /usr/include /usr/local/include "$OPS"
hunt "op_tiling_context_builder.h" "op_tiling_context_builder.h" "$CANN" "$OPS"
hunt "op_impl_space_registry_v2.h" "op_impl_space_registry_v2.h" "$CANN"
hunt "platform_ascendc.h" "platform_ascendc.h" "$CANN"
hunt "platform_infos_def.h" "platform_infos_def.h" "$CANN"
hunt "tiling_base.h(op_host)" "tiling_base.h" "$OPS/common/include"

echo
echo "=== build tree ==="
ls -d "$OPS/build" 2>/dev/null || echo "no $OPS/build"
find "$OPS/build" -name 'libophost_transformer_ut.so' 2>/dev/null | head -2
echo
echo "=== faker objects already built? ==="
find "$OPS/build" -name '*tiling_context_faker*' -o -name '*tiling_case_executor*' 2>/dev/null | head -10
echo
echo "=== candidate lib dirs ==="
for d in "$CANN/lib64" "$CANN/x86_64-linux/lib64"; do
  [ -d "$d" ] && echo "  $d"
done
echo
echo "=== key libs ==="
for l in tiling_api runtime ascendalog metadef register opp_registry graph platform unified_dlog rt2_registry_static; do
  f=$(find "$CANN" -name "lib${l}.so" -o -name "lib${l}.a" 2>/dev/null | head -1)
  printf '  %-22s %s\n' "$l" "${f:-MISSING}"
done
