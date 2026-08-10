#!/usr/bin/env bash
set -eo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/run_env.sh"
export PATH="/work/venv-acp/bin:/usr/bin:/bin:$PATH"
P="/work/ops-transformer/attention/flash_attention_score_grad"
LOG="$RUN_LOG/logs/tg_init_continue.log"
exec > >(tee -a "$LOG") 2>&1

run() { echo ">>> acp $*"; acp "$@" --project "$P"; }

run advance bind
run run-action semantic_bind
run advance gate
run run-action integrity_gate
run run-action init_audit
run run-action init_audit --finalize
run advance confirm
run run-action human_confirm
run run-action human_confirm --finalize
run complete
echo "TG-INIT DONE"
