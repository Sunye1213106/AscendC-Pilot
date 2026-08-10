#!/usr/bin/env bash
set -eo pipefail
SRC=/work/ops-transformer/attention/flash_attention_score_grad/.ascendc-pilot/arch35/tg/plan
cp "$SRC/levels/L0/coverage_obligations.yaml" "$SRC/coverage_obligations.yaml"
source /mnt/d/PR-review/AscendC-Pilot/artifacts/fa-pr13/full_closure_run_20260810/run_env.sh
export PATH="/work/venv-acp/bin:/usr/bin:/bin:$PATH"
P=/work/ops-transformer/attention/flash_attention_score_grad
acp retry-after-environment-fix --project "$P" || true
acp run-action plan_build --project "$P" || true
acp run-action plan_build --finalize --project "$P" || true
acp status --project "$P" | head -c 1800
echo
ls -la "$SRC/coverage_obligations.yaml"
