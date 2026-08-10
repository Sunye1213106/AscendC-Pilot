#!/usr/bin/env bash
set -eo pipefail
source /mnt/d/PR-review/AscendC-Pilot/artifacts/fa-pr13/full_closure_run_20260810/run_env.sh
export PATH="/work/venv-acp/bin:/usr/bin:/bin:$PATH"
P=/work/ops-transformer/attention/flash_attention_score_grad
LOG=/mnt/d/PR-review/AscendC-Pilot/artifacts/fa-pr13/full_closure_run_20260810/logs/parent_auto_approve.log
exec > >(tee -a "$LOG") 2>&1
acp retry-after-environment-fix --project "$P" || true
# Fresh prepare then finalize (auto-approve)
acp run-action plan_approve --project "$P"
acp run-action plan_approve --finalize --project "$P"
acp status --project "$P" | head -c 1500
echo
