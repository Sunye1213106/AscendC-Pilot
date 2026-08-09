#!/usr/bin/env bash
# Replay the ground-truth CSV through the driver.
#
# The cache directory is an input, not a property of this script: it used to be
# one checkout's absolute path, which silently replayed someone else's corpus.
# Pass it as $1 or set REPLAY_CACHE_DIR.
set -eu
source /work/wsl/setup/env.sh

C="${1:-${REPLAY_CACHE_DIR:-}}"
if [ -z "$C" ]; then
  echo "usage: $0 <cache_dir>   (or set REPLAY_CACHE_DIR)" >&2
  exit 2
fi
if [ ! -f "$C/replay_in.csv" ]; then
  echo "missing $C/replay_in.csv" >&2
  exit 2
fi

tr -d '\r' < "$C/replay_in.csv" > /tmp/gt_in.csv
LD_PRELOAD="$REPLAY_PRELOAD${LD_PRELOAD:+:$LD_PRELOAD}" \
  "$REPLAY_BIN" /tmp/gt_in.csv "$C/replay_out.csv" "$REPLAY_SO" > /tmp/gt_log.txt 2>&1
echo "rc=$? lines=$(wc -l < "$C/replay_out.csv")"
