#!/usr/bin/env bash
set -eo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/run_env.sh"
export PATH="/work/venv-acp/bin:/usr/bin:/bin:$PATH"
P="/work/ops-transformer/attention/flash_attention_score_grad"
run() { echo ">>> acp $*"; acp "$@" --project "$P"; }

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
