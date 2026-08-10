#!/usr/bin/env bash
set -euo pipefail
source /work/venv-acp/bin/activate
if [ -f /usr/local/Ascend/cann/set_env.sh ]; then
  set +u
  # shellcheck disable=SC1091
  source /usr/local/Ascend/cann/set_env.sh || true
  set -u
fi
if [ -f /work/wsl/setup/env.sh ]; then
  set +u
  # shellcheck disable=SC1091
  source /work/wsl/setup/env.sh || true
  set -u
fi
export ASCENDC_PROJECT_ROOT=/work/ops-transformer/attention/flash_attention_score_grad
export UO_OP_DIR=$ASCENDC_PROJECT_ROOT
export UO_OPERATOR=flash_attention_score_grad
export UO_ARCH=arch35
export UO_OPS_ROOT=/work/ops-transformer
export OPS_TRANSFORMER_ROOT=/work/ops-transformer
export UO_REPLAY_DISTRO=Ubuntu-2204
export UO_REPLAY_HOST=native
export PYTHONPATH=/mnt/d/PR-review/AscendC-Pilot:/mnt/d/PR-review/AscendC-Pilot/pilot:/mnt/d/PR-review/AscendC-Pilot/engines/testcase-generation:/mnt/d/PR-review/AscendC-Pilot/engines/understand-operator/src:/mnt/d/PR-review/AscendC-Pilot/scripts
export ACP=/work/venv-acp/bin/acp
export RUN_LOG=/mnt/d/PR-review/AscendC-Pilot/artifacts/fa-pr13/full_closure_run_20260810
export LOG_DIR=$RUN_LOG/logs
mkdir -p "$LOG_DIR"
cd "$ASCENDC_PROJECT_ROOT"
