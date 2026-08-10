#!/usr/bin/env bash
set -o pipefail
source /mnt/d/PR-review/AscendC-Pilot/artifacts/fa-pr13/full_closure_run_20260810/run_env.sh
export PATH="/work/venv-acp/bin:/usr/bin:/bin:$PATH"
P=/work/ops-transformer/attention/flash_attention_score_grad
LOG=/mnt/d/PR-review/AscendC-Pilot/artifacts/fa-pr13/full_closure_run_20260810/logs/parent_auto_approve3.log
exec > >(tee -a "$LOG") 2>&1
acp status --project "$P" | head -c 400; echo
acp run-action plan_approve --project "$P" || true
acp run-action plan_approve --finalize --project "$P" || true
echo ====FINAL_STATUS====
acp status --project "$P" | python3 -c 'import sys,json;d=json.load(sys.stdin);print("phase",d.get("phase"),"status",d.get("status"));lf=d.get("last_failure") or {};print("err",lf.get("error_code"), (lf.get("message_zh") or "")[:240]);print("passed",d.get("passed_gates"));print("failed",d.get("failed_gates"))'
