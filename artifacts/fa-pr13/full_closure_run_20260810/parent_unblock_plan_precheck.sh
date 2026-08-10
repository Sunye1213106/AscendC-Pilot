#!/usr/bin/env bash
# Verify plan_precheck unblocked, then hand off to composer.
set -eo pipefail
source /mnt/d/PR-review/AscendC-Pilot/artifacts/fa-pr13/full_closure_run_20260810/run_env.sh
export PATH="/work/venv-acp/bin:/usr/bin:/bin:$PATH"
P="/work/ops-transformer/attention/flash_attention_score_grad"
LOG="/mnt/d/PR-review/AscendC-Pilot/artifacts/fa-pr13/full_closure_run_20260810/logs/parent_unblock_plan_precheck.log"
mkdir -p "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1

echo "=== status ==="
acp status --project "$P" || true
echo "=== rework / retry plan_precheck ==="
acp rework --project "$P" 2>/dev/null || true
acp run-action plan_precheck --project "$P"
acp run-action plan_precheck --finalize --project "$P"
echo "=== status after ==="
acp status --project "$P" | head -c 2000
echo
echo "PARENT_UNBLOCK_DONE"
