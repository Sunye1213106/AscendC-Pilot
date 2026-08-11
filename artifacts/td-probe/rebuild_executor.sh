#!/usr/bin/env bash
# Rebuild tiling_case_executor.o (null-slot fix) and link replay_main.
set -euo pipefail
source /usr/local/Ascend/cann/set_env.sh >/dev/null 2>&1 || true
CANN="${ASCEND_HOME_PATH:?}"
OPS=${OPS_ROOT:-/work/ops-transformer}
B="$OPS/build/tests/ut/framework_normal/op_host"
COMMON="$B/CMakeFiles/transformer_op_tiling_ut_common_obj.dir/__/common"
SRC="$OPS/tests/ut/framework_normal/common/tiling_case_executor.cpp"

tr -d '\r' < "$SRC" > /tmp/tiling_case_executor.cpp
/usr/bin/c++ -std=c++17 -O2 -fPIC -w -c \
  -DBUILD_OPEN_PROJECT -DCFG_BUILD_DEBUG -DNOT_DYNAMIC_COMPILE \
  -D_GLIBCXX_USE_CXX11_ABI=0 -Dnlohmann=ascend_nlohmann -DLOG_CPP \
  -Dgoogle=ascend_private \
  -DOPS_UTILS_LOG_PACKAGE_TYPE='"[Custom]"' \
  -DOPS_UTILS_LOG_SUB_MOD_NAME='"OP_TILING"' \
  -I"$OPS" -I"$OPS/third_party/json/include" \
  -I"$OPS/tests/ut/framework_normal/common" -I"$OPS/common/include" \
  -I"$OPS/third_party/opbase/include/op_common" \
  -I"$OPS/third_party/opbase/include/op_common/op_host" \
  -I"$CANN/include/base/context_builder" -I"$CANN/pkg_inc" \
  -I"$CANN/include/ascendc/basic_api" -I"$CANN/x86_64-linux/include/exe_graph" \
  -I"$CANN/x86_64-linux/include/op_common" -I"$CANN/x86_64-linux/include/op_common/op_host" \
  -I"$CANN/x86_64-linux/pkg_inc" -I"$CANN/x86_64-linux/pkg_inc/runtime" \
  -I"$CANN/include/platform" -I"$CANN/include/external" \
  -isystem "$OPS/third_party/lib_cache/gtest/include" \
  -isystem "$CANN/include" -isystem "$CANN/x86_64-linux/include" \
  -isystem "$CANN/include/base" -isystem "$CANN/pkg_inc/base" \
  -isystem "$CANN/include/exe_graph" \
  /tmp/tiling_case_executor.cpp -o "$COMMON/tiling_case_executor.cpp.o"
echo "recompiled $COMMON/tiling_case_executor.cpp.o"
bash /mnt/d/PR-review/AscendC-Pilot/scripts/replay/wsl/build_replay.sh
