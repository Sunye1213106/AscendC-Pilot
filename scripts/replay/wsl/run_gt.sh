#!/usr/bin/env bash
# Replay the ground-truth CSV through the driver, straight to .probe_cache.
set -eu
source /work/wsl/setup/env.sh
C=/mnt/d/PR-review/AscendC-Pilot/.probe_cache
tr -d '\r' < "$C/replay_in.csv" > /tmp/gt_in.csv
LD_PRELOAD="$REPLAY_PRELOAD${LD_PRELOAD:+:$LD_PRELOAD}" \
  "$REPLAY_BIN" /tmp/gt_in.csv "$C/replay_out.csv" "$REPLAY_SO" > /tmp/gt_log.txt 2>&1
echo "rc=$? lines=$(wc -l < "$C/replay_out.csv")"
