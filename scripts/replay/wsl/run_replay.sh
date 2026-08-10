#!/usr/bin/env bash
# The entry point `runner.py` invokes for one batch.
#
# Called as: bash run_replay.sh <in.csv> <out.csv> <log.txt> <with_log>
# and the driver underneath wants a different shape:
#           fag_replay <in.csv> <out.csv> <libophost_transformer_ut.so> [op]
#
# Two streams have to end up in one file. The driver prints `###CASE` and
# `###DONE` on stdout; the tiling's own OP_LOGD lines -- which is where
# splitAxis, isExceedL2Cache and sparseType actually come from -- only reach
# stdout when slog is told to print there. `log_protocol.yaml` scrapes both out
# of the same text, so both are redirected into <log.txt> together.
#
# `BATCH_DONE` goes to this script's stdout, not into the log: that is the
# marker runner.py checks to tell a finished batch from a driver that never
# started.
set -uo pipefail

IN=${1:?usage: run_replay.sh <in.csv> <out.csv> <log.txt> [with_log]}
OUT=${2:?missing out.csv}
LOG=${3:?missing log.txt}
WITH_LOG=${4:-1}

source /usr/local/Ascend/cann/set_env.sh >/dev/null 2>&1 || true

OPS=${OPS_ROOT:-/work/ops-transformer}
BIN=${REPLAY_BIN:-/work/replay/build/fag_replay}
SO=${REPLAY_SO:-$OPS/build/tests/ut/framework_normal/op_host/libophost_transformer_ut.so}
OP_NAME=${REPLAY_OP_NAME:-FlashAttentionScoreGrad}

for f in "$BIN" "$SO"; do
  if [ ! -f "$f" ]; then
    echo "replay: missing $f" >&2
    echo "  driver:   bash scripts/replay/wsl/build_replay.sh" >&2
    echo "  host so:  ./build.sh --ophost_test --ops=<op> --soc=<soc> --noexec" >&2
    exit 2
  fi
done

# The unit tests hand tiling 4096 bytes. The TND swizzle path stores 129 prefix
# sums twice and InitTilingData fails at that size, so every key behind it went
# missing rather than reported unreachable.
export REPLAY_TILING_DATA_SIZE=${REPLAY_TILING_DATA_SIZE:-65536}

if [ "$WITH_LOG" = "1" ]; then
  export ASCEND_SLOG_PRINT_TO_STDOUT=1
  export ASCEND_GLOBAL_LOG_LEVEL=1
else
  # The marks still have to come through; only the operator's own logging is
  # silenced, which is what makes a no-log batch faster.
  export ASCEND_SLOG_PRINT_TO_STDOUT=1
  export ASCEND_GLOBAL_LOG_LEVEL=3
fi

mkdir -p "$(dirname "$LOG")" "$(dirname "$OUT")"

"$BIN" "$IN" "$OUT" "$SO" "$OP_NAME" >"$LOG" 2>&1
rc=$?

if [ $rc -ne 0 ]; then
  echo "replay: driver exited $rc" >&2
  tail -n 40 "$LOG" >&2
  exit $rc
fi

echo "BATCH_DONE rc=$rc cases=$(grep -c '^###DONE' "$LOG" 2>/dev/null || echo 0)"
