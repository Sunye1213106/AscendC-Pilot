#!/usr/bin/env bash
# The entry point `runner.py` invokes for one batch.
#
# Called as: bash run_replay.sh <in.csv> <out.csv> <log.txt> <with_log>
# CANN comes from the generated extract wrapper (REPLAY_CANN_ENV), not
# /usr/local/Ascend/cann/set_env.sh.
set -uo pipefail

IN=${1:?usage: run_replay.sh <in.csv> <out.csv> <log.txt> [with_log]}
OUT=${2:?missing out.csv}
LOG=${3:?missing log.txt}
WITH_LOG=${4:-1}

if [ -n "${REPLAY_CANN_ENV:-}" ] && [ -f "$REPLAY_CANN_ENV" ]; then
  # shellcheck disable=SC1090
  source "$REPLAY_CANN_ENV" >/dev/null 2>&1 || true
fi

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

export REPLAY_TILING_DATA_SIZE=${REPLAY_TILING_DATA_SIZE:-65536}
export REPLAY_DUMP_TD=${REPLAY_DUMP_TD:-1}

if [ "$WITH_LOG" = "1" ]; then
  export ASCEND_SLOG_PRINT_TO_STDOUT=1
  export ASCEND_GLOBAL_LOG_LEVEL=1
else
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
