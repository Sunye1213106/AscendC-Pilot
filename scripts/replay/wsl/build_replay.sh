#!/usr/bin/env bash
# Build the replay driver against the already-built UT framework.
#
# The two framework translation units (`tiling_case_executor`,
# `tiling_context_faker`) are reused as the objects the UT build already
# produced rather than recompiled: they need gtest and the exact ABI flags the
# tree was configured with, and linking the existing objects is what keeps this
# in step with whatever `build.sh --ophost_test` last produced.
#
# Run: wsl -d Ubuntu-22.04 -e bash build_replay.sh [src.cpp] [out_bin]
set -euo pipefail

source /usr/local/Ascend/cann/set_env.sh >/dev/null 2>&1 || true
CANN="${ASCEND_HOME_PATH:?set_env.sh did not define ASCEND_HOME_PATH}"
OPS=${OPS_ROOT:-/work/ops-transformer}
B="$OPS/build/tests/ut/framework_normal/op_host"
FAG="$OPS/build/attention/flash_attention_score_grad/op_host"

SRC=${1:-/mnt/d/PR-review/AscendC-Pilot/scripts/replay/wsl/replay_main.cpp}
OUT=${2:-/work/wsl/bin/replay_main}

COMMON="$B/CMakeFiles/transformer_op_tiling_ut_common_obj.dir/__/common"
for o in "$COMMON/tiling_case_executor.cpp.o" "$COMMON/tiling_context_faker.cpp.o"; do
  [ -f "$o" ] || { echo "missing framework object: $o" >&2
                   echo "run ./build.sh --ophost_test first" >&2; exit 2; }
done
[ -f "$B/libophost_transformer_ut.so" ] || {
  echo "missing $B/libophost_transformer_ut.so" >&2; exit 2; }

# The operator objects the framework leans on for logging and shape helpers.
OPBASE=$(find "$FAG/CMakeFiles/opbase_util_objs.dir" \
              "$FAG/CMakeFiles/opbase_infer_objs.dir" -name '*.o' 2>/dev/null)

# CRLF survives the trip from Windows and makes the compiler report errors on
# lines that look fine.
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
tr -d '\r' < "$SRC" > "$WORK/replay_main.cpp"

# Mirrors flags.make for transformer_op_tiling_ut_common_obj: the ABI macro and
# the nlohmann rename are not optional, the objects were built with them.
mkdir -p "$(dirname "$OUT")"
set -x
/usr/bin/c++ -std=c++17 -O2 -fPIC -w \
  -DBUILD_OPEN_PROJECT -DCFG_BUILD_DEBUG -DNOT_DYNAMIC_COMPILE \
  -D_GLIBCXX_USE_CXX11_ABI=0 -Dnlohmann=ascend_nlohmann -DLOG_CPP \
  -Dgoogle=ascend_private \
  -DOPS_UTILS_LOG_PACKAGE_TYPE='"[Custom]"' \
  -DOPS_UTILS_LOG_SUB_MOD_NAME='"OP_TILING"' \
  -I"$OPS" \
  -I"$OPS/third_party/json/include" \
  -I"$OPS/tests/ut/framework_normal/common" \
  -I"$OPS/common/include" \
  -I"$OPS/third_party/opbase/include/op_common" \
  -I"$OPS/third_party/opbase/include/op_common/op_host" \
  -I"$CANN/include/base/context_builder" \
  -I"$CANN/pkg_inc" \
  -I"$CANN/include/ascendc/basic_api" \
  -I"$CANN/x86_64-linux/include/exe_graph" \
  -I"$CANN/x86_64-linux/include/op_common" \
  -I"$CANN/x86_64-linux/include/op_common/op_host" \
  -I"$CANN/x86_64-linux/pkg_inc" \
  -I"$CANN/x86_64-linux/pkg_inc/runtime" \
  -I"$CANN/include/platform" \
  -I"$CANN/include/external" \
  -isystem "$OPS/third_party/lib_cache/gtest/include" \
  -isystem "$CANN/include" \
  -isystem "$CANN/x86_64-linux/include" \
  -isystem "$CANN/include/base" \
  -isystem "$CANN/pkg_inc/base" \
  -isystem "$CANN/include/exe_graph" \
  "$WORK/replay_main.cpp" \
  "$COMMON/tiling_case_executor.cpp.o" \
  "$COMMON/tiling_context_faker.cpp.o" \
  $OPBASE \
  -o "$OUT" \
  -L"$CANN/x86_64-linux/lib64" \
  -Wl,-rpath,"$CANN/x86_64-linux/lib64:$B:$CANN/lib64" \
  -Wl,--no-as-needed "$B/libophost_transformer_ut.so" -lascendalog -ldl \
  -Wl,--as-needed \
  "$CANN/x86_64-linux/lib64/libtiling_api.a" \
  -Wl,--no-as-needed "$CANN/x86_64-linux/lib64/libmetadef.so" -Wl,--as-needed \
  "$CANN/x86_64-linux/lib64/libregister.so" \
  "$CANN/x86_64-linux/lib64/libopp_registry.so" \
  "$CANN/x86_64-linux/lib64/libgraph.so" \
  "$CANN/x86_64-linux/lib64/libplatform.so" \
  "$OPS/third_party/lib_cache/gtest/lib/libgtest.a" \
  -lunified_dlog "$CANN/lib64/libc_sec.so" -lgcov -lpthread
set +x

echo "built $OUT"
ls -la "$OUT"
