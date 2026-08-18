#!/usr/bin/env bash
# Build the replay driver against the already-built UT framework.
#
# CANN comes from the UO extracted package (cann-asc-devkit / metadef / …),
# never from /usr/local/Ascend. Bootstrap writes cann_env.sh and sources it
# before invoking this script; REPLAY_CANN_ENV is the fallback.
#
# Run: bash build_replay.sh [src.cpp] [out_bin]
set -euo pipefail

if [ -n "${REPLAY_CANN_ENV:-}" ] && [ -f "$REPLAY_CANN_ENV" ]; then
  # shellcheck disable=SC1090
  source "$REPLAY_CANN_ENV" >/dev/null 2>&1 || true
fi
: "${CANN_PKG_ROOT:?CANN_PKG_ROOT missing — TG bootstrap must generate cann_env.sh}"
HOST="${CANN_HOST:-x86_64-linux}"
DEVKIT="${CANN_PKG_ROOT}/cann-asc-devkit/${HOST}"
META="${CANN_PKG_ROOT}/cann-metadef/${HOST}"
RT="${CANN_PKG_ROOT}/cann-npu-runtime/${HOST}"
OPBASE="${CANN_PKG_ROOT}/cann-opbase/${HOST}"
CANN="${ASCEND_HOME_PATH:-$DEVKIT}"

OPS=${OPS_ROOT:-/work/ops-transformer}
B="$OPS/build/tests/ut/framework_normal/op_host"
FAG="$OPS/build/attention/flash_attention_score_grad/op_host"

SRC=${1:-}
OUT=${2:-}
if [ -z "$SRC" ] || [ -z "$OUT" ]; then
  echo "usage: build_replay.sh <src.cpp> <out_bin>" >&2
  exit 2
fi

libdir() {
  local d
  for d in "$@"; do
    if [ -d "$d" ]; then
      printf '%s' "$d"
      return 0
    fi
  done
  return 1
}

find_lib() {
  local name=$1
  local hit
  hit=$(find "$CANN_PKG_ROOT" -name "$name" 2>/dev/null | head -1)
  if [ -n "$hit" ]; then
    printf '%s' "$hit"
  fi
}

LIB64=$(libdir "$DEVKIT/lib64" "$DEVKIT/lib" "$META/lib64" "$RT/lib64" || true)
if [ -z "${LIB64:-}" ]; then
  echo "no lib64 under extracted CANN_PKG_ROOT=$CANN_PKG_ROOT" >&2
  exit 2
fi

COMMON="$B/CMakeFiles/transformer_op_tiling_ut_common_obj.dir/__/common"
for o in "$COMMON/tiling_case_executor.cpp.o" "$COMMON/tiling_context_faker.cpp.o"; do
  [ -f "$o" ] || { echo "missing framework object: $o" >&2
                   echo "run ./build.sh --ophost_test first" >&2; exit 2; }
done
[ -f "$B/libophost_transformer_ut.so" ] || {
  echo "missing $B/libophost_transformer_ut.so" >&2; exit 2; }

OPBASE_OBJS=$(find "$FAG/CMakeFiles/opbase_util_objs.dir" \
              "$FAG/CMakeFiles/opbase_infer_objs.dir" -name '*.o' 2>/dev/null || true)

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
tr -d '\r' < "$SRC" > "$WORK/replay_main.cpp"

TILING_API=$(find_lib "libtiling_api.a")
METADEF=$(find_lib "libmetadef.so")
REGISTER=$(find_lib "libregister.so")
OPP_REG=$(find_lib "libopp_registry.so")
GRAPH=$(find_lib "libgraph.so")
PLATFORM=$(find_lib "libplatform.so")
CSEC=$(find_lib "libc_sec.so")
GTEST="$OPS/third_party/lib_cache/gtest/lib/libgtest.a"

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
  -I"$DEVKIT/include/base/context_builder" \
  -I"$DEVKIT/pkg_inc" \
  -I"$DEVKIT/include/ascendc/basic_api" \
  -I"$DEVKIT/include" \
  -I"$META/include" \
  -I"$META/include/exe_graph" \
  -I"$OPBASE/include" \
  -I"$OPBASE/include/op_common" \
  -I"$OPBASE/include/op_common/op_host" \
  -I"$RT/include" \
  -I"$RT/include/base" \
  -isystem "$OPS/third_party/lib_cache/gtest/include" \
  -isystem "$DEVKIT/include" \
  -isystem "$META/include" \
  "$WORK/replay_main.cpp" \
  "$COMMON/tiling_case_executor.cpp.o" \
  "$COMMON/tiling_context_faker.cpp.o" \
  $OPBASE_OBJS \
  -o "$OUT" \
  -L"$LIB64" \
  -Wl,-rpath,"$LIB64:$B" \
  -Wl,--no-as-needed "$B/libophost_transformer_ut.so" -lascendalog -ldl \
  -Wl,--as-needed \
  ${TILING_API:+"$TILING_API"} \
  ${METADEF:+-Wl,--no-as-needed "$METADEF" -Wl,--as-needed} \
  ${REGISTER:+"$REGISTER"} \
  ${OPP_REG:+"$OPP_REG"} \
  ${GRAPH:+"$GRAPH"} \
  ${PLATFORM:+"$PLATFORM"} \
  ${GTEST:+"$GTEST"} \
  -lunified_dlog ${CSEC:+"$CSEC"} -lgcov -lpthread
set +x

echo "built $OUT"
ls -la "$OUT"
