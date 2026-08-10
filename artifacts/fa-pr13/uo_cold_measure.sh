#!/usr/bin/env bash
# Cold-start wall-clock measurement for uo-init extract, comparable to
# rebuild_uo_construct.log (baseline: extract_host_bundle TOTAL 311.9s).
set -uo pipefail

source /usr/local/Ascend/cann/set_env.sh
source /work/venv-acp/bin/activate
source /work/wsl/setup/env.sh

PILOT=/mnt/d/PR-review/AscendC-Pilot
OP=/work/ops-transformer/attention/flash_attention_score_grad
ARCH=arch35
OP_NAME=flash_attention_score_grad
OUT="$PILOT/artifacts/fa-pr13"
LABEL="${1:-python}"
LOG="$OUT/uo_cold_${LABEL}.log"

export PATH="/work/venv-acp/bin:$PATH"
export PYTHONPATH="$PILOT:$PILOT/engines/testcase-generation:$PILOT/scripts:$PILOT/engines/understand-operator/src:$PILOT/pilot:${PYTHONPATH:-}"
export ASCENDC_PROJECT_ROOT="$OP"
export UO_OP_DIR="$OP"
export UO_OPERATOR="$OP_NAME"
export UO_ARCH="$ARCH"
export UO_OPS_ROOT=/work/ops-transformer
export OPS_TRANSFORMER_ROOT=/work/ops-transformer
export UO_TIMING=1

exec > >(tee "$LOG") 2>&1

echo "== label=$LABEL UO_NATIVE_WALK=${UO_NATIVE_WALK:-unset} UO_INIT_PROFILE=${UO_INIT_PROFILE:-default} =="
python -c "import uo_init, sys; print('uo_init', uo_init.__file__); print(sys.version)"
nproc

echo "== wipe TU cache + uo products (TRUE cold) =="
rm -rf "$OP/.ascendc-pilot/$ARCH/uo" "$OP/.ascendc-pilot/uo"
mkdir -p "$OP/.ascendc-pilot/uo" "$OP/.ascendc-pilot/$ARCH/uo"
du -sh "$OP/.ascendc-pilot/$ARCH/uo" 2>/dev/null || true

echo "== prepare + extract (timed) =="
/usr/bin/time -v python - <<'PY' 2>&1 | tail -n 200
import json, time
from pathlib import Path
from uo_init import codemap_engines as ce

OP = Path("/work/ops-transformer/attention/flash_attention_score_grad")
ctx = {
    "op_name": "flash_attention_score_grad",
    "architecture": "arch35",
    "arch_dir": "arch35",
    "auto_accept_clean": True,
    "force_confirm": True,
    "decision": "continue",
    "run_id": f"coldmeasure_{int(time.time())}",
}
for name, fn in [("prepare", ce.prepare), ("extract", ce.extract)]:
    t0 = time.time()
    print(f"-- {name} --", flush=True)
    out = fn(OP, ctx)
    print(f"[measure] {name} wall={time.time()-t0:.2f}s ok={out.get('ok')} err={out.get('error')}", flush=True)
    if not out.get("ok"):
        raise SystemExit(f"{name} failed")
PY

echo "DONE $LABEL"
