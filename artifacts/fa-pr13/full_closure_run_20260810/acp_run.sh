#!/usr/bin/env bash
# Usage: acp_run.sh <phase> <action> [extra acp args...]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=run_env.sh
source "$SCRIPT_DIR/run_env.sh"
PHASE="${1:?phase required}"
ACTION="${2:?action required}"
shift 2
TS="$(date +%Y%m%dT%H%M%S)"
LOG="$LOG_DIR/${PHASE}_${ACTION}_${TS}.log"
T0="$(date -Iseconds)"
T0_EPOCH=$(date +%s)
echo "=== START $PHASE/$ACTION at $T0 ===" | tee "$LOG"
set +e
$ACP run-action "$ACTION" "$@" 2>&1 | tee -a "$LOG"
EC=${PIPESTATUS[0]}
set -e
T1="$(date -Iseconds)"
T1_EPOCH=$(date +%s)
WALL=$((T1_EPOCH - T0_EPOCH))
echo "=== END $PHASE/$ACTION ec=$EC wall_s=$WALL at $T1 ===" | tee -a "$LOG"
echo "$T0|$T1|$WALL|$EC|$PHASE|$ACTION|$LOG"
exit $EC
