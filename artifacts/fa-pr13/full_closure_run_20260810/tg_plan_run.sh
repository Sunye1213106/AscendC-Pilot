#!/usr/bin/env bash
set -eo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/run_env.sh"
export PATH="/work/venv-acp/bin:/usr/bin:/bin:$PATH"
P="/work/ops-transformer/attention/flash_attention_score_grad"
LOG="$RUN_LOG/logs/tg_plan_run.log"
exec > >(tee -a "$LOG") 2>&1

run() { echo ">>> acp $*"; acp "$@" --project "$P"; }

run start tg-plan --op-name flash_attention_score_grad --architecture arch35 --level L0
run run-action plan_intent
run run-action plan_intent --finalize
run advance scope
run run-action plan_scope
run advance gate
run run-action plan_precheck
run advance build
run run-action plan_build
run advance approve
run run-action plan_approve
run run-action plan_approve --finalize
run complete
echo "TG-PLAN DONE"
