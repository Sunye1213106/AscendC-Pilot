#!/usr/bin/env bash
# Clean historical TG/UO products, install fresh .uo, run tg-init -> tg-plan -> tg-solve
set -euo pipefail

source /work/venv-acp/bin/activate
source /work/wsl/setup/env.sh

PILOT=/mnt/d/PR-review/AscendC-Pilot
# Prefer the WSL ops checkout used by replay_main / REPLAY_SO
OP=/work/ops-transformer/attention/flash_attention_score_grad
FRESH_UO="$PILOT/artifacts/fa-pr13/flash_attention_score_grad.arch35.uo"
ARCH=arch35
OP_NAME=flash_attention_score_grad

export PATH="/work/venv-acp/bin:$PATH"
export PYTHONPATH="$PILOT:$PILOT/engines/testcase-generation:$PILOT/scripts:$PILOT/engines/understand-operator/src:$PILOT/pilot:${PYTHONPATH:-}"
export ASCENDC_PROJECT_ROOT="$OP"
export UO_OP_DIR="$OP"
export UO_OPERATOR="$OP_NAME"
export UO_ARCH="$ARCH"
export UO_OPS_ROOT=/work/ops-transformer
export OPS_TRANSFORMER_ROOT=/work/ops-transformer
export UO_REPLAY_DISTRO="${UO_REPLAY_DISTRO:-Ubuntu-22.04}"

echo "== env =="
which acp
which python
python -c "import ascendc_pilot,testcase_agent,uo_init; print('imports ok')"
test -x "$REPLAY_BIN"
test -f "$FRESH_UO"
test -d "$OP"

echo "== clean historical products under operator =="
# Keep directory scaffold if needed, wipe UO/TG/CE/run state for this op
if [[ -d "$OP/.ascendc-pilot" ]]; then
  # backup nothing; user asked to delete historical products
  rm -rf \
    "$OP/.ascendc-pilot/uo" \
    "$OP/.ascendc-pilot/tg" \
    "$OP/.ascendc-pilot/$ARCH" \
    "$OP/.ascendc-pilot/runs" \
    "$OP/.ascendc-pilot/state" \
    "$OP/.ascendc-pilot/context" \
    "$OP/.ascendc-pilot/memory" \
    "$OP/.ascendc-pilot/ce"
fi
mkdir -p "$OP/.ascendc-pilot/uo"

echo "== install fresh UO only =="
cp -f "$FRESH_UO" "$OP/.ascendc-pilot/uo/${OP_NAME}.${ARCH}.uo"
ls -la "$OP/.ascendc-pilot/uo/"
python - <<'PY'
from pathlib import Path
from uo_init.store.reader import find_uo_product, read_meta
op = Path("/work/ops-transformer/attention/flash_attention_score_grad")
p = find_uo_product(op, op_name="flash_attention_score_grad", architecture="arch35")
print("uo_product", p)
print("meta", {k: read_meta(p).get(k) for k in ("schema","op_name","architecture","entity_count","relation_count")})
PY

echo "== acp doctor =="
acp doctor --project "$OP" || true

echo "== START tg-init =="
acp start tg-init --project "$OP" --op-name "$OP_NAME" --architecture "$ARCH" --force-new
acp status --project "$OP" || true
acp next --project "$OP" || true

run_det() {
  local action="$1"
  echo "== run-action $action =="
  acp run-action "$action" --project "$OP"
  acp run-action "$action" --project "$OP" --finalize
}

# deterministic tg-init chain (skip interactive until human_confirm)
for action in init_intent kb_check contract_build semantic_bind bind_merge mid_nest integrity_gate; do
  # some actions may be skipped by mode overlay; tolerate non-fatal
  if acp next --project "$OP" 2>/dev/null | tee /tmp/acp_next.txt | grep -q "$action\|allowed\|next"; then
    :
  fi
  if acp run-action "$action" --project "$OP"; then
    acp run-action "$action" --project "$OP" --finalize || true
  else
    echo "WARN: prepare failed for $action (may be inactive in mode)"
  fi
  acp advance --project "$OP" || true
done

echo "== tg-init artifacts =="
find "$OP/.ascendc-pilot" -type f \( -name '*.yaml' -o -name '*.json' -o -name '*.uo' \) | sort | head -80

echo "DONE_TG_INIT_PHASE"
