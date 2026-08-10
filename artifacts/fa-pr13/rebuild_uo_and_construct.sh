#!/usr/bin/env bash
# Rebuild FAG .uo via uo-init engines, then sample/full construct coverage.
set -euo pipefail

source /usr/local/Ascend/cann/set_env.sh
source /work/venv-acp/bin/activate
source /work/wsl/setup/env.sh

PILOT=/mnt/d/PR-review/AscendC-Pilot
OP=/work/ops-transformer/attention/flash_attention_score_grad
ARCH=arch35
OP_NAME=flash_attention_score_grad
OUT="$PILOT/artifacts/fa-pr13"
LOG="$OUT/rebuild_uo_construct.log"

export PATH="/work/venv-acp/bin:$PATH"
export PYTHONPATH="$PILOT:$PILOT/engines/testcase-generation:$PILOT/scripts:$PILOT/engines/understand-operator/src:$PILOT/pilot:${PYTHONPATH:-}"
export ASCENDC_PROJECT_ROOT="$OP"
export UO_OP_DIR="$OP"
export UO_OPERATOR="$OP_NAME"
export UO_ARCH="$ARCH"
export UO_OPS_ROOT=/work/ops-transforme
export OPS_TRANSFORMER_ROOT=/work/ops-transforme

exec > >(tee "$LOG") 2>&1

echo "== env =="
echo "ASCEND_HOME_PATH=$ASCEND_HOME_PATH"
which python
python -c "import ascendc_pilot,testcase_agent,uo_init; print('imports ok', uo_init.__file__)"
python - <<'PY'
try:
    import clang.cindex as ci
    print("libclang", ci.conf.get_filename())
except Exception as e:
    print("libclang_error", e)
PY
ls -la "$OP/op_kernel/arch35/flash_attention_score_grad_template_tiling_key.h"

echo "== wipe historical products (keep TU cache) =="
# TU cache lives at .ascendc-pilot/<arch>/uo/cache/tu — wiping it forces
# full libclang rewalk (~5min on FAG). Preserve cache across rebuilds.
CACHE_BAK=$(mktemp -d)
if [[ -d "$OP/.ascendc-pilot/$ARCH/uo/cache" ]]; then
  cp -a "$OP/.ascendc-pilot/$ARCH/uo/cache" "$CACHE_BAK/cache"
  echo "preserved cache -> $CACHE_BAK/cache"
fi
rm -rf \
  "$OP/.ascendc-pilot/uo" \
  "$OP/.ascendc-pilot/tg" \
  "$OP/.ascendc-pilot/$ARCH/tg" \
  "$OP/.ascendc-pilot/$ARCH/ce" \
  "$OP/.ascendc-pilot/$ARCH/memory" \
  "$OP/.ascendc-pilot/$ARCH/runs" \
  "$OP/.ascendc-pilot/$ARCH/state" \
  "$OP/.ascendc-pilot/$ARCH/context" \
  "$OP/.ascendc-pilot/runs" \
  "$OP/.ascendc-pilot/state" \
  "$OP/.ascendc-pilot/context" \
  "$OP/.ascendc-pilot/memory" \
  "$OP/.ascendc-pilot/ce"
# Remove arch uo product tree but restore cache
rm -rf "$OP/.ascendc-pilot/$ARCH/uo"
mkdir -p "$OP/.ascendc-pilot/uo" "$OP/.ascendc-pilot/$ARCH/uo"
if [[ -d "$CACHE_BAK/cache" ]]; then
  mv "$CACHE_BAK/cache" "$OP/.ascendc-pilot/$ARCH/uo/cache"
  echo "restored TU cache"
fi
rm -rf "$CACHE_BAK"

echo "== uo-init: prepare → extract → analyze → resolve → commit → review =="
python - <<'PY'
import json
from pathlib import Path
from uo_init import codemap_engines as ce
from uo_init.store.reader import find_uo_product, load_view_blob, read_meta

OP = Path("/work/ops-transformer/attention/flash_attention_score_grad")
import time
ctx = {
    "op_name": "flash_attention_score_grad",
    "architecture": "arch35",
    "arch_dir": "arch35",
    "auto_accept_clean": True,
    "force_confirm": True,
    "decision": "continue",
    "run_id": f"rebuild_{int(time.time())}",
}
steps = [
    ("prepare", ce.prepare),
    ("extract", ce.extract),
    ("analyze", ce.analyze),
    ("resolve", ce.resolve),
    ("commit", ce.commit),
    ("review", ce.review),
]
for name, fn in steps:
    print(f"-- {name} --", flush=True)
    out = fn(OP, ctx)
    brief = {
        "ok": out.get("ok"),
        "engine": out.get("engine"),
        "error": out.get("error"),
        "failed_step": out.get("failed_step"),
        "path": out.get("path"),
        "gap_count": out.get("gap_count"),
        "verdict": out.get("verdict"),
        "summary": out.get("summary"),
    }
    print(json.dumps(brief, ensure_ascii=False, default=str)[:4000], flush=True)
    if not out.get("ok"):
        # resolve may leave gaps; still try commit if extract/analyze ok
        if name == "resolve":
            print("WARN: resolve not ok; continuing to commit", flush=True)
            continue
        if name in {"prepare", "extract", "analyze", "commit"}:
            raise SystemExit(f"{name} failed")
        print(f"WARN: {name} not ok; continuing", flush=True)

p = find_uo_product(OP, op_name="flash_attention_score_grad", architecture="arch35")
print("PRODUCT", p)
if p is None:
    raise SystemExit("missing .uo product")
meta = read_meta(p)
print("META", {k: meta.get(k) for k in ("schema", "op_name", "architecture", "entity_count", "relation_count")})
space = load_view_blob(p, "tiling/exhaustive_key_space.yaml") or {}
host = load_view_blob(p, "ir/tg_host_view.yaml") or {}
graph = load_view_blob(p, "ir/operator_graph.yaml") or {}
print("VIEWS", {
    "legal_key_count": (space or {}).get("legal_key_count"),
    "host_fields": len((host or {}).get("fields") or []),
    "graph_fp": (graph or {}).get("fingerprint"),
})
PY

# copy product into artifacts
PRODUCT="$OP/.ascendc-pilot/uo/${OP_NAME}.${ARCH}.uo"
cp -f "$PRODUCT" "$OUT/${OP_NAME}.${ARCH}.uo"
ls -la "$PRODUCT" "$OUT/${OP_NAME}.${ARCH}.uo"

echo "== tg-init engines =="
python - <<'PY'
import json
from pathlib import Path
from ascendc_pilot.paths import ensure_agent_layout, tg_root
from ascendc_pilot.actions import engines as E

OP = Path("/work/ops-transformer/attention/flash_attention_score_grad")
ensure_agent_layout(OP, arch="arch35")
ctx = {
    "op_name": "flash_attention_score_grad",
    "architecture": "arch35",
    "mode": "tilingkey_full_coverage",
    "level": "L0",
}
for name, fn in [
    ("init_intent", E._run_tg_init_intent),
    ("kb_check", E._run_tg_kb_check),
    ("contract_build", E._run_tg_contract_build),
    ("semantic_bind", E._run_tg_semantic_bind),
    ("integrity", E._run_tg_integrity),
]:
    print(f"-- {name} --", flush=True)
    out = fn(OP, ctx)
    print(json.dumps({k: out.get(k) for k in ("ok", "error", "mode", "engine", "field_count")}, ensure_ascii=False, default=str)[:3000], flush=True)
    if name == "contract_build":
        payload = out.get("payload") or {}
        print("declared", (payload.get("declared_set") or {}), flush=True)

tg = tg_root(OP, arch="arch35")
for rel in [
    "init/uo_ready.yaml",
    "contract/tilingkey_contract.yaml",
    "realization/binding_inventory.yaml",
]:
    p = tg / rel
    print(rel, "OK" if p.is_file() else "MISSING", p.stat().st_size if p.is_file() else 0)
PY

echo "== construct coverage over D =="
python - <<'PY'
import json
import os
import time
from pathlib import Path

from uo_init.store.reader import find_uo_product
from uo_init.tg_projection import legal_key_rows
from testcase_agent.closure import construct as C

OP = Path("/work/ops-transformer/attention/flash_attention_score_grad")
os.environ["ASCENDC_PROJECT_ROOT"] = str(OP)
os.environ["UO_OPERATOR"] = "flash_attention_score_grad"
os.environ["UO_ARCH"] = "arch35"

product = find_uo_product(OP, op_name="flash_attention_score_grad", architecture="arch35")
rows = legal_key_rows(product)
print("D_rows", len(rows), flush=True)

# Prefer dims dict on rows; fall back to decode if available
ok = 0
empty = 0
errors = 0
samples_ok = []
samples_empty = []
t0 = time.time()
# Full pass can be large; report progress every 500
for i, row in enumerate(rows):
    dims = row.get("dims") or row.get("values") or {}
    if not isinstance(dims, dict) or not dims:
        empty += 1
        if len(samples_empty) < 5:
            samples_empty.append({"i": i, "row": row, "reason": "no_dims"})
        continue
    t = {str(k): str(v) for k, v in dims.items()}
    try:
        cases = C.build(t, seed=0)
    except Exception as exc:
        errors += 1
        if len(samples_empty) < 8:
            samples_empty.append({"i": i, "key": row.get("tiling_key"), "error": str(exc)[:200]})
        continue
    if cases:
        ok += 1
        if len(samples_ok) < 3:
            samples_ok.append({"key": row.get("tiling_key"), "n_cases": len(cases), "dims": t})
    else:
        empty += 1
        if len(samples_empty) < 8:
            samples_empty.append({"i": i, "key": row.get("tiling_key"), "dims": t, "reason": "no_case"})
    if (i + 1) % 500 == 0:
        print(f"progress {i+1}/{len(rows)} ok={ok} empty={empty} errors={errors}", flush=True)

elapsed = time.time() - t0
report = {
    "D": len(rows),
    "construct_ok": ok,
    "construct_empty": empty,
    "construct_errors": errors,
    "elapsed_sec": round(elapsed, 2),
    "samples_ok": samples_ok,
    "samples_fail": samples_empty,
    "traces_tail": (C.last_traces() or [])[-3:],
}
out = Path("/mnt/d/PR-review/AscendC-Pilot/artifacts/fa-pr13/construct_coverage.json")
out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2)[:6000])
print("WROTE", out)
PY

echo "DONE"
