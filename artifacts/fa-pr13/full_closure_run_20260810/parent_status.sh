#!/usr/bin/env bash
set -euo pipefail
source /mnt/d/PR-review/AscendC-Pilot/artifacts/fa-pr13/full_closure_run_20260810/run_env.sh
export PATH="/work/venv-acp/bin:/usr/bin:/bin:$PATH"
P=/work/ops-transformer/attention/flash_attention_score_grad
acp status --project "$P" | tee /tmp/acp_st.json | head -c 3000
echo
python3 - <<'PY'
import json
d=json.load(open("/tmp/acp_st.json"))
print("phase=", d.get("phase"), "status=", d.get("status"))
print("next=", (d.get("todo") or {}).get("next_actions"))
print("phases=", [(p["id"], p["status"]) for p in ((d.get("todo") or {}).get("phases") or [])])
lf=d.get("last_failure") or {}
print("last_failure=", lf.get("error_code"), lf.get("message_zh","")[:200] if lf else None)
PY
echo TRANSCRIPT_LINES=$(wc -l < /mnt/c/Users/sunye/.cursor/projects/d-PR-review/agent-transcripts/4120a2b1-5405-47bb-a9cf-a145777f2d0a/subagents/04f96c1e-83ed-4966-8497-640daf094315.jsonl)
ls -lt --time-style=long-iso /mnt/d/PR-review/AscendC-Pilot/artifacts/fa-pr13/full_closure_run_20260810/logs | head -8
