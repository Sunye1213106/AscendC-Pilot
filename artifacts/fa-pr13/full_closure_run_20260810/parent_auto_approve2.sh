#!/usr/bin/env bash
set -eo pipefail
source /mnt/d/PR-review/AscendC-Pilot/artifacts/fa-pr13/full_closure_run_20260810/run_env.sh
export PATH="/work/venv-acp/bin:/usr/bin:/bin:$PATH"
P=/work/ops-transformer/attention/flash_attention_score_grad
LOG=/mnt/d/PR-review/AscendC-Pilot/artifacts/fa-pr13/full_closure_run_20260810/logs/parent_auto_approve2.log
exec > >(tee -a "$LOG") 2>&1
acp retry-after-environment-fix --project "$P"
acp run-action plan_approve --project "$P"
acp run-action plan_approve --finalize --project "$P"
echo ====
acp status --project "$P" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("phase"),d.get("status"));print((d.get("last_failure") or {}).get("message_zh","")[:300]);print("passed",d.get("passed_gates"))'
