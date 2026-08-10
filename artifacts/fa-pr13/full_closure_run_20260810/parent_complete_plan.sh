#!/usr/bin/env bash
set -o pipefail
source /mnt/d/PR-review/AscendC-Pilot/artifacts/fa-pr13/full_closure_run_20260810/run_env.sh
export PATH="/work/venv-acp/bin:/usr/bin:/bin:$PATH"
P=/work/ops-transformer/attention/flash_attention_score_grad
LOG=/mnt/d/PR-review/AscendC-Pilot/artifacts/fa-pr13/full_closure_run_20260810/logs/parent_complete_plan.log
exec > >(tee -a "$LOG") 2>&1
acp complete --project "$P" || true
acp status --project "$P" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("workflow_id"),d.get("phase"),d.get("status"));print("passed",d.get("passed_gates"))'
echo DONE
